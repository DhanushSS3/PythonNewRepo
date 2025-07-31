# app/services/swap_service.py

import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.database.models import UserOrder, User
from app.crud.crud_order import get_all_system_open_orders
from app.core.cache import get_group_symbol_settings_cache, get_external_symbol_info_cache
from app.core.firebase import get_latest_market_data
from app.crud import group as crud_group  # Add this import to fetch group info
from app.services.portfolio_calculator import _convert_to_usd

# logger = logging.getLogger(__name__)
from app.core.logging_config import swap_logger as logger

def convert_show_points_to_decimal(show_points: int) -> Decimal:
    """
    Convert show_points integer to decimal value.
    show_points = 3 -> 0.001
    show_points = 5 -> 0.00001
    etc.
    """
    if show_points <= 0:
        return Decimal("0.001")  # Default fallback
    
    # Calculate the decimal value based on show_points
    # show_points = 3 -> 0.001 (3 decimal places)
    # show_points = 5 -> 0.00001 (5 decimal places)
    decimal_places = show_points
    decimal_value = Decimal("1") / (Decimal("10") ** decimal_places)
    return decimal_value

async def apply_daily_swap_charges_for_all_open_orders(db: AsyncSession, redis_client: Redis):
    """
    Applies daily swap charges to all open orders.
    This function is intended to be called daily at UTC 00:00 by a scheduler.
    New Formula: swap_charge = swap_points * point_value * lots
    Where: point_value = contract_size * show_points * conversion_rate
    """
    logger.info("[SWAP] Starting daily swap charge application process.")
    open_orders: List[UserOrder] = await get_all_system_open_orders(db)

    logger.info(f"[SWAP] Number of open orders fetched: {len(open_orders)}")

    if not open_orders:
        logger.info("[SWAP] No open orders found. Exiting swap charge process.")
        return

    processed_count = 0
    failed_count = 0

    for order in open_orders:
        try:
            # Access the eager-loaded user object
            user = order.user
            if not user:
                # Fallback if user was not loaded for some reason (should not happen with eager loading)
                logger.warning(f"User data not loaded for order {order.order_id} (user_id: {order.order_user_id}). Attempting direct fetch.")
                user_db_obj = await db.get(User, order.order_user_id)
                if not user_db_obj:
                    logger.warning(f"User ID {order.order_user_id} not found for order {order.order_id}. Skipping swap.")
                    failed_count += 1
                    continue
                user = user_db_obj

            user_group_name = getattr(user, 'group_name', 'default')
            order_symbol = order.order_company_name.upper()
            order_quantity = Decimal(str(order.order_quantity))
            order_type = order.order_type.upper()

            # 1. Get Group Settings for swap rates
            group_settings = await get_group_symbol_settings_cache(redis_client, user_group_name, order_symbol)
            if not group_settings:
                logger.warning(f"Group settings not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for order {order.order_id}.")
                failed_count += 1
                continue

            swap_buy_rate_str = group_settings.get('swap_buy', "0.0")
            swap_sell_rate_str = group_settings.get('swap_sell', "0.0")

            try:
                swap_buy_rate = Decimal(str(swap_buy_rate_str))
                swap_sell_rate = Decimal(str(swap_sell_rate_str))
            except InvalidOperation as e:
                logger.error(f"Error converting swap rates from group settings for order {order.order_id}: {e}. Rates: buy='{swap_buy_rate_str}', sell='{swap_sell_rate_str}'. Skipping.")
                failed_count +=1
                continue

            # Choose swap points based on order type
            swap_points = swap_buy_rate if order_type == "BUY" else swap_sell_rate
            logger.info(f"[SWAP] Order {order.order_id}: Using swap_points={swap_points} for order_type={order_type}")

            # 2. Get contract_size from external_symbol_info cache
            external_symbol_info = await get_external_symbol_info_cache(redis_client, order_symbol)
            if not external_symbol_info:
                logger.warning(f"External symbol info not found for symbol '{order_symbol}'. Skipping swap for order {order.order_id}.")
                failed_count += 1
                continue

            contract_size = external_symbol_info.get('contract_size')
            if not contract_size:
                logger.warning(f"Contract size not found in external symbol info for symbol '{order_symbol}'. Skipping swap for order {order.order_id}.")
                failed_count += 1
                continue

            try:
                contract_size = Decimal(str(contract_size))
            except (InvalidOperation, TypeError) as e:
                logger.error(f"Error converting contract_size to Decimal for order {order.order_id}: {e}. Contract size: {contract_size}. Skipping.")
                failed_count += 1
                continue

            logger.info(f"[SWAP] Order {order.order_id}: Contract size from external symbol info: {contract_size}")

            # 3. Get show_points from groups table
            group_obj = await crud_group.get_group_by_symbol_and_name(db, symbol=order_symbol, name=user_group_name)
            if not group_obj:
                logger.warning(f"Group not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for order {order.order_id}.")
                failed_count += 1
                continue

            show_points = getattr(group_obj, 'show_points', None)
            if show_points is None:
                logger.warning(f"Show points not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for order {order.order_id}.")
                failed_count += 1
                continue

            try:
                show_points = int(show_points)
            except (ValueError, TypeError) as e:
                logger.error(f"Error converting show_points to int for order {order.order_id}: {e}. Show points: {show_points}. Skipping.")
                failed_count += 1
                continue

            # Convert show_points to decimal value
            show_points_decimal = convert_show_points_to_decimal(show_points)
            logger.info(f"[SWAP] Order {order.order_id}: Show points={show_points} -> decimal value={show_points_decimal}")

            # 4. Calculate point_value = contract_size * show_points * conversion_rate
            # First calculate: contract_size * show_points
            point_value_raw = contract_size * show_points_decimal
            logger.info(f"[SWAP] Order {order.order_id}: Point value raw (contract_size * show_points) = {contract_size} * {show_points_decimal} = {point_value_raw}")

            # 5. Convert point_value to USD if needed using profit currency from external_symbol_info
            profit_currency = external_symbol_info.get('profit', 'USD')
            if not profit_currency:
                profit_currency = 'USD'  # Default fallback
            
            point_value_usd = point_value_raw

            if profit_currency.upper() != 'USD':
                try:
                    point_value_usd = await _convert_to_usd(
                        point_value_raw,
                        profit_currency.upper(),
                        user.id,
                        order.order_id,
                        "Point Value",
                        db,
                        redis_client
                    )
                    logger.info(f"[SWAP] Order {order.order_id}: Converted point value to USD: {point_value_raw} {profit_currency} -> {point_value_usd} USD")
                except Exception as e:
                    logger.error(f"[SWAP] Failed to convert point value to USD for order {order.order_id}: {e}")
                    failed_count += 1
                    continue
            else:
                logger.info(f"[SWAP] Order {order.order_id}: Point value already in USD: {point_value_usd}")

            # 6. Calculate final swap charge: swap_charge = swap_points * point_value * lots
            swap_charge = swap_points * point_value_usd * order_quantity
            logger.info(f"[SWAP] Order {order.order_id}: Final swap charge calculation: {swap_points} * {point_value_usd} * {order_quantity} = {swap_charge}")

            # Quantize to match UserOrder.swap field's precision
            swap_charge = swap_charge.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP)
            logger.info(f"[SWAP] Order {order.order_id}: Quantized swap charge: {swap_charge}")

            # 7. Update Order's Swap Field
            current_swap_value = order.swap if order.swap is not None else Decimal("0.0")
            order.swap = current_swap_value + swap_charge

            logger.info(f"Order {order.order_id}: Applied daily swap charge: {swap_charge}. Old Swap: {current_swap_value}, New Swap: {order.swap}.")
            processed_count += 1

        except Exception as e:
            logger.error(f"General failure to process swap for order {order.order_id}: {e}", exc_info=True)
            failed_count += 1
            # Continue to the next order even if one fails

    if open_orders:
        try:
            await db.commit()
            logger.info(f"[SWAP] Daily swap charges committed to DB. Processed: {processed_count}, Failed: {failed_count}.")
        except Exception as e:
            logger.error(f"[SWAP] Failed to commit swap charges to DB: {e}", exc_info=True)
            await db.rollback()
            logger.info("[SWAP] Database transaction rolled back due to commit error in swap service.")
    else:
        logger.info("[SWAP] No open orders were processed, so no database commit was attempted for swap charges.")
    logger.info("[SWAP] Daily swap charge application process completed.")