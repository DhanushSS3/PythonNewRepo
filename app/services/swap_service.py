# app/services/swap_service.py

import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.database.models import UserOrder, User, DemoUser, DemoUserOrder
from app.crud.crud_order import get_all_open_orders
from app.core.cache import get_group_symbol_settings_cache, get_external_symbol_info_cache, set_external_symbol_info_cache
from app.core.firebase import get_latest_market_data
from app.crud import group as crud_group  # Add this import to fetch group info
from app.crud.external_symbol_info import get_external_symbol_info_by_symbol  # Add this import for database fallback
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

def get_user_type_from_order(order) -> str:
    """
    Determine user type from order object.
    Returns 'live' or 'demo' based on the order's table/model.
    """
    if hasattr(order, '__class__'):
        if order.__class__.__name__ == 'DemoUserOrder':
            return 'demo'
        elif order.__class__.__name__ == 'UserOrder':
            return 'live'
    
    # Fallback: check if order has user_type attribute
    if hasattr(order, 'user_type'):
        return str(order.user_type).lower()
    
    # Default to live if we can't determine
    return 'live'

async def update_user_cache_after_swap(user_id: int, db: AsyncSession, redis_client: Redis, user_type: str):
    """
    Update user cache after swap charges are applied.
    Updates both static orders cache and balance/margin cache.
    """
    try:
        logger.info(f"[SWAP] Updating cache for user {user_id} (type: {user_type}) after swap charges")
        
        # Import cache functions
        from app.core.cache import set_user_static_orders_cache, set_user_balance_margin_cache, get_user_data_cache
        from app.api.v1.endpoints.orders import update_user_static_orders
        from app.services.order_processing import calculate_total_user_margin
        
        # Update static orders cache
        await update_user_static_orders(user_id, db, redis_client, user_type)
        logger.info(f"[SWAP] Updated static orders cache for user {user_id}")
        
        # Update balance/margin cache
        try:
            # Get fresh user data for balance
            user_data = await get_user_data_cache(redis_client, user_id, db, user_type)
            if user_data:
                balance = user_data.get('wallet_balance', '0.0')
                
                # Calculate total user margin including all symbols
                total_user_margin = await calculate_total_user_margin(db, redis_client, user_id, user_type)
                
                # Update the balance/margin cache
                await set_user_balance_margin_cache(redis_client, user_id, balance, total_user_margin, user_type)
                logger.info(f"[SWAP] Updated balance/margin cache for user {user_id}: balance={balance}, margin={total_user_margin}")
            else:
                logger.warning(f"[SWAP] Could not get user data for balance/margin cache update for user {user_id}")
                
        except Exception as e:
            logger.error(f"[SWAP] Error updating balance/margin cache for user {user_id}: {e}", exc_info=True)
            
    except Exception as e:
        logger.error(f"[SWAP] Error updating cache for user {user_id}: {e}", exc_info=True)

async def apply_daily_swap_charges_for_all_open_orders(db: AsyncSession, redis_client: Redis):
    """
    Applies daily swap charges to all open orders for both live and demo users.
    This function is intended to be called daily at UTC 00:00 by a scheduler.
    New Formula: swap_charge = swap_points * point_value * lots
    Where: point_value = contract_size * show_points * conversion_rate
    """
    logger.info("[SWAP] Starting daily swap charge application process.")
    
    # Get both live and demo open orders
    live_orders, demo_orders = await get_all_open_orders(db)
    
    logger.info(f"[SWAP] Number of live open orders fetched: {len(live_orders)}")
    logger.info(f"[SWAP] Number of demo open orders fetched: {len(demo_orders)}")
    
    total_orders = len(live_orders) + len(demo_orders)
    if total_orders == 0:
        logger.info("[SWAP] No open orders found. Exiting swap charge process.")
        return

    processed_count = 0
    failed_count = 0
    
    # Track users whose cache needs to be updated
    users_to_update_cache = set()  # Set of (user_id, user_type) tuples

    # Process live orders
    for order in live_orders:
        try:
            # Access the eager-loaded user object
            user = order.user
            if not user:
                # Fallback if user was not loaded for some reason (should not happen with eager loading)
                logger.warning(f"User data not loaded for live order {order.order_id} (user_id: {order.order_user_id}). Attempting direct fetch.")
                try:
                    user_db_obj = await db.get(User, order.order_user_id)
                    if not user_db_obj:
                        logger.warning(f"User ID {order.order_user_id} not found for live order {order.order_id}. Skipping swap.")
                        failed_count += 1
                        continue
                    user = user_db_obj
                except Exception as user_fetch_error:
                    logger.error(f"Error fetching user for live order {order.order_id}: {user_fetch_error}")
                    failed_count += 1
                    continue

            user_group_name = getattr(user, 'group_name', 'default')
            order_symbol = order.order_company_name.upper()
            order_quantity = Decimal(str(order.order_quantity))
            order_type = order.order_type.upper()

            # 1. Get Group Settings for swap rates
            group_settings = await get_group_symbol_settings_cache(redis_client, user_group_name, order_symbol)
            if not group_settings:
                logger.warning(f"Group settings not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for live order {order.order_id}.")
                failed_count += 1
                continue

            swap_buy_rate_str = group_settings.get('swap_buy', "0.0")
            swap_sell_rate_str = group_settings.get('swap_sell', "0.0")

            try:
                swap_buy_rate = Decimal(str(swap_buy_rate_str))
                swap_sell_rate = Decimal(str(swap_sell_rate_str))
            except InvalidOperation as e:
                logger.error(f"Error converting swap rates from group settings for live order {order.order_id}: {e}. Rates: buy='{swap_buy_rate_str}', sell='{swap_sell_rate_str}'. Skipping.")
                failed_count +=1
                continue

            # Choose swap points based on order type
            swap_points = swap_buy_rate if order_type == "BUY" else swap_sell_rate
            logger.info(f"[SWAP] Live order {order.order_id}: Using swap_points={swap_points} for order_type={order_type}")

            # 2. Get contract_size from external_symbol_info cache
            external_symbol_info = await get_external_symbol_info_cache(redis_client, order_symbol)
            if not external_symbol_info:
                logger.warning(f"External symbol info not found in cache for symbol '{order_symbol}'. Attempting to fetch from database and cache it.")
                
                # Fallback: Fetch from database and cache it
                try:
                    db_symbol_info = await get_external_symbol_info_by_symbol(db, order_symbol)
                    if db_symbol_info:
                        # Convert database object to dictionary format for caching
                        external_symbol_info = {
                            'contract_size': db_symbol_info.contract_size,
                            'profit': db_symbol_info.profit,
                            'digit': db_symbol_info.digit,
                            'fix_symbol': db_symbol_info.fix_symbol
                        }
                        
                        # Cache the fetched data
                        await set_external_symbol_info_cache(redis_client, order_symbol, external_symbol_info)
                        logger.info(f"[SWAP] Successfully fetched and cached external symbol info for symbol '{order_symbol}' from database.")
                    else:
                        logger.warning(f"External symbol info not found in database for symbol '{order_symbol}'. Using default values.")
                        # Use default values for missing symbol info
                        external_symbol_info = {
                            'contract_size': Decimal('100000'),  # Default contract size
                            'profit': 'USD',  # Default profit currency
                            'digit': Decimal('5'),  # Default digit
                            'fix_symbol': order_symbol
                        }
                        logger.info(f"[SWAP] Using default external symbol info for symbol '{order_symbol}': {external_symbol_info}")
                except Exception as db_error:
                    logger.error(f"Error fetching external symbol info from database for symbol '{order_symbol}': {db_error}. Using default values.")
                    # Use default values for missing symbol info
                    external_symbol_info = {
                        'contract_size': Decimal('100000'),  # Default contract size
                        'profit': 'USD',  # Default profit currency
                        'digit': Decimal('5'),  # Default digit
                        'fix_symbol': order_symbol
                    }
                    logger.info(f"[SWAP] Using default external symbol info for symbol '{order_symbol}' due to database error: {external_symbol_info}")

            contract_size = external_symbol_info.get('contract_size')
            if not contract_size:
                logger.warning(f"Contract size not found in external symbol info for symbol '{order_symbol}'. Using default value.")
                contract_size = Decimal('100000')  # Default contract size

            try:
                contract_size = Decimal(str(contract_size))
            except (InvalidOperation, TypeError) as e:
                logger.error(f"Error converting contract_size to Decimal for live order {order.order_id}: {e}. Contract size: {contract_size}. Using default value.")
                contract_size = Decimal('100000')  # Default contract size

            logger.info(f"[SWAP] Live order {order.order_id}: Contract size from external symbol info: {contract_size}")

            # 3. Get show_points from groups table
            group_obj = await crud_group.get_group_by_symbol_and_name(db, symbol=order_symbol, name=user_group_name)
            if not group_obj:
                logger.warning(f"Group not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for live order {order.order_id}.")
                failed_count += 1
                continue

            show_points = getattr(group_obj, 'show_points', None)
            if show_points is None:
                logger.warning(f"Show points not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for live order {order.order_id}.")
                failed_count += 1
                continue

            try:
                show_points = int(show_points)
            except (ValueError, TypeError) as e:
                logger.error(f"Error converting show_points to int for live order {order.order_id}: {e}. Show points: {show_points}. Skipping.")
                failed_count += 1
                continue

            # Convert show_points to decimal value
            show_points_decimal = convert_show_points_to_decimal(show_points)
            logger.info(f"[SWAP] Live order {order.order_id}: Show points={show_points} -> decimal value={show_points_decimal}")

            # 4. Calculate point_value = contract_size * show_points * conversion_rate
            # First calculate: contract_size * show_points
            point_value_raw = contract_size * show_points_decimal
            logger.info(f"[SWAP] Live order {order.order_id}: Point value raw (contract_size * show_points) = {contract_size} * {show_points_decimal} = {point_value_raw}")

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
                    logger.info(f"[SWAP] Live order {order.order_id}: Converted point value to USD: {point_value_raw} {profit_currency} -> {point_value_usd} USD")
                except Exception as e:
                    logger.error(f"[SWAP] Failed to convert point value to USD for live order {order.order_id}: {e}")
                    failed_count += 1
                    continue
            else:
                logger.info(f"[SWAP] Live order {order.order_id}: Point value already in USD: {point_value_usd}")

            # 6. Calculate final swap charge: swap_charge = swap_points * point_value * lots
            swap_charge = swap_points * point_value_usd * order_quantity
            logger.info(f"[SWAP] Live order {order.order_id}: Final swap charge calculation: {swap_points} * {point_value_usd} * {order_quantity} = {swap_charge}")

            # Quantize to match UserOrder.swap field's precision
            swap_charge = swap_charge.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP)
            logger.info(f"[SWAP] Live order {order.order_id}: Quantized swap charge: {swap_charge}")

            # 7. Update Order's Swap Field
            current_swap_value = order.swap if order.swap is not None else Decimal("0.0")
            order.swap = current_swap_value + swap_charge

            logger.info(f"Live order {order.order_id}: Applied daily swap charge: {swap_charge}. Old Swap: {current_swap_value}, New Swap: {order.swap}.")
            processed_count += 1
            
            # Track for cache update (live user)
            users_to_update_cache.add((order.order_user_id, 'live'))

        except Exception as e:
            logger.error(f"General failure to process swap for live order {order.order_id}: {e}", exc_info=True)
            failed_count += 1
            # Continue to the next order even if one fails

    # Process demo orders
    for order in demo_orders:
        try:
            # For demo orders, we need to fetch the user separately since there's no eager loading
            from app.crud.user import get_demo_user_by_id
            user = await get_demo_user_by_id(db, order.order_user_id)
            if not user:
                logger.warning(f"Demo user ID {order.order_user_id} not found for demo order {order.order_id}. Skipping swap.")
                failed_count += 1
                continue

            user_group_name = getattr(user, 'group_name', 'default')
            order_symbol = order.order_company_name.upper()
            order_quantity = Decimal(str(order.order_quantity))
            order_type = order.order_type.upper()

            # 1. Get Group Settings for swap rates
            group_settings = await get_group_symbol_settings_cache(redis_client, user_group_name, order_symbol)
            if not group_settings:
                logger.warning(f"Group settings not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for demo order {order.order_id}.")
                failed_count += 1
                continue

            swap_buy_rate_str = group_settings.get('swap_buy', "0.0")
            swap_sell_rate_str = group_settings.get('swap_sell', "0.0")

            try:
                swap_buy_rate = Decimal(str(swap_buy_rate_str))
                swap_sell_rate = Decimal(str(swap_sell_rate_str))
            except InvalidOperation as e:
                logger.error(f"Error converting swap rates from group settings for demo order {order.order_id}: {e}. Rates: buy='{swap_buy_rate_str}', sell='{swap_sell_rate_str}'. Skipping.")
                failed_count +=1
                continue

            # Choose swap points based on order type
            swap_points = swap_buy_rate if order_type == "BUY" else swap_sell_rate
            logger.info(f"[SWAP] Demo order {order.order_id}: Using swap_points={swap_points} for order_type={order_type}")

            # 2. Get contract_size from external_symbol_info cache
            external_symbol_info = await get_external_symbol_info_cache(redis_client, order_symbol)
            if not external_symbol_info:
                logger.warning(f"External symbol info not found in cache for symbol '{order_symbol}'. Attempting to fetch from database and cache it.")
                
                # Fallback: Fetch from database and cache it
                try:
                    db_symbol_info = await get_external_symbol_info_by_symbol(db, order_symbol)
                    if db_symbol_info:
                        # Convert database object to dictionary format for caching
                        external_symbol_info = {
                            'contract_size': db_symbol_info.contract_size,
                            'profit': db_symbol_info.profit,
                            'digit': db_symbol_info.digit,
                            'fix_symbol': db_symbol_info.fix_symbol
                        }
                        
                        # Cache the fetched data
                        await set_external_symbol_info_cache(redis_client, order_symbol, external_symbol_info)
                        logger.info(f"[SWAP] Successfully fetched and cached external symbol info for symbol '{order_symbol}' from database.")
                    else:
                        logger.warning(f"External symbol info not found in database for symbol '{order_symbol}'. Using default values.")
                        # Use default values for missing symbol info
                        external_symbol_info = {
                            'contract_size': Decimal('100000'),  # Default contract size
                            'profit': 'USD',  # Default profit currency
                            'digit': Decimal('5'),  # Default digit
                            'fix_symbol': order_symbol
                        }
                        logger.info(f"[SWAP] Using default external symbol info for symbol '{order_symbol}': {external_symbol_info}")
                except Exception as db_error:
                    logger.error(f"Error fetching external symbol info from database for symbol '{order_symbol}': {db_error}. Using default values.")
                    # Use default values for missing symbol info
                    external_symbol_info = {
                        'contract_size': Decimal('100000'),  # Default contract size
                        'profit': 'USD',  # Default profit currency
                        'digit': Decimal('5'),  # Default digit
                        'fix_symbol': order_symbol
                    }
                    logger.info(f"[SWAP] Using default external symbol info for symbol '{order_symbol}' due to database error: {external_symbol_info}")

            contract_size = external_symbol_info.get('contract_size')
            if not contract_size:
                logger.warning(f"Contract size not found in external symbol info for symbol '{order_symbol}'. Using default value.")
                contract_size = Decimal('100000')  # Default contract size

            try:
                contract_size = Decimal(str(contract_size))
            except (InvalidOperation, TypeError) as e:
                logger.error(f"Error converting contract_size to Decimal for demo order {order.order_id}: {e}. Contract size: {contract_size}. Using default value.")
                contract_size = Decimal('100000')  # Default contract size

            logger.info(f"[SWAP] Demo order {order.order_id}: Contract size from external symbol info: {contract_size}")

            # 3. Get show_points from groups table
            group_obj = await crud_group.get_group_by_symbol_and_name(db, symbol=order_symbol, name=user_group_name)
            if not group_obj:
                logger.warning(f"Group not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for demo order {order.order_id}.")
                failed_count += 1
                continue

            show_points = getattr(group_obj, 'show_points', None)
            if show_points is None:
                logger.warning(f"Show points not found for group '{user_group_name}', symbol '{order_symbol}'. Skipping swap for demo order {order.order_id}.")
                failed_count += 1
                continue

            try:
                show_points = int(show_points)
            except (ValueError, TypeError) as e:
                logger.error(f"Error converting show_points to int for demo order {order.order_id}: {e}. Show points: {show_points}. Skipping.")
                failed_count += 1
                continue

            # Convert show_points to decimal value
            show_points_decimal = convert_show_points_to_decimal(show_points)
            logger.info(f"[SWAP] Demo order {order.order_id}: Show points={show_points} -> decimal value={show_points_decimal}")

            # 4. Calculate point_value = contract_size * show_points * conversion_rate
            # First calculate: contract_size * show_points
            point_value_raw = contract_size * show_points_decimal
            logger.info(f"[SWAP] Demo order {order.order_id}: Point value raw (contract_size * show_points) = {contract_size} * {show_points_decimal} = {point_value_raw}")

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
                    logger.info(f"[SWAP] Demo order {order.order_id}: Converted point value to USD: {point_value_raw} {profit_currency} -> {point_value_usd} USD")
                except Exception as e:
                    logger.error(f"[SWAP] Failed to convert point value to USD for demo order {order.order_id}: {e}")
                    failed_count += 1
                    continue
            else:
                logger.info(f"[SWAP] Demo order {order.order_id}: Point value already in USD: {point_value_usd}")

            # 6. Calculate final swap charge: swap_charge = swap_points * point_value * lots
            swap_charge = swap_points * point_value_usd * order_quantity
            logger.info(f"[SWAP] Demo order {order.order_id}: Final swap charge calculation: {swap_points} * {point_value_usd} * {order_quantity} = {swap_charge}")

            # Quantize to match DemoUserOrder.swap field's precision
            swap_charge = swap_charge.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP)
            logger.info(f"[SWAP] Demo order {order.order_id}: Quantized swap charge: {swap_charge}")

            # 7. Update Order's Swap Field
            current_swap_value = order.swap if order.swap is not None else Decimal("0.0")
            order.swap = current_swap_value + swap_charge

            logger.info(f"Demo order {order.order_id}: Applied daily swap charge: {swap_charge}. Old Swap: {current_swap_value}, New Swap: {order.swap}.")
            processed_count += 1
            
            # Track for cache update (demo user)
            users_to_update_cache.add((order.order_user_id, 'demo'))

        except Exception as e:
            logger.error(f"General failure to process swap for demo order {order.order_id}: {e}", exc_info=True)
            failed_count += 1
            # Continue to the next order even if one fails

    if total_orders > 0:
        try:
            await db.commit()
            logger.info(f"[SWAP] Daily swap charges committed to DB. Processed: {processed_count}, Failed: {failed_count}.")
            
            # Update cache for all affected users
            logger.info(f"[SWAP] Updating cache for {len(users_to_update_cache)} users after swap charges")
            for user_id, user_type in users_to_update_cache:
                try:
                    await update_user_cache_after_swap(user_id, db, redis_client, user_type)
                except Exception as cache_error:
                    logger.error(f"[SWAP] Failed to update cache for user {user_id} (type: {user_type}): {cache_error}", exc_info=True)
            
        except Exception as e:
            logger.error(f"[SWAP] Failed to commit swap charges to DB: {e}", exc_info=True)
            await db.rollback()
            logger.info("[SWAP] Database transaction rolled back due to commit error in swap service.")
    else:
        logger.info("[SWAP] No open orders were processed, so no database commit was attempted for swap charges.")
    logger.info("[SWAP] Daily swap charge application process completed.")