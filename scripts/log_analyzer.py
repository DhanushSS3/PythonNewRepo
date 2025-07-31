#!/usr/bin/env python3
"""
Log Analyzer for OTP and Email Logs

This script analyzes the specialized log files for OTPs and emails to provide
insights into usage patterns, success rates, and potential issues.
"""

import os
import re
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import argparse
from pathlib import Path

class LogAnalyzer:
    def __init__(self, logs_dir="logs"):
        self.logs_dir = Path(logs_dir)
        self.otp_dir = self.logs_dir / "otps"
        self.email_dir = self.logs_dir / "emails"
        
    def parse_log_line(self, line):
        """Parse a log line and extract timestamp and message."""
        try:
            # Expected format: 2024-01-01 12:00:00 - INFO - logger_name - MESSAGE
            parts = line.strip().split(" - ", 3)
            if len(parts) >= 4:
                timestamp_str = f"{parts[0]} {parts[1]}"
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                message = parts[3]
                return timestamp, message
        except Exception as e:
            print(f"Error parsing line: {line.strip()} - {e}")
        return None, None
    
    def analyze_otp_logs(self, hours=24):
        """Analyze OTP generation and verification logs."""
        print(f"\n=== OTP Analysis (Last {hours} hours) ===")
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        otp_stats = {
            'generated': 0,
            'verified': 0,
            'failed': 0,
            'by_user_type': defaultdict(int),
            'by_email': defaultdict(int)
        }
        
        # Analyze OTP generation logs
        otp_gen_file = self.otp_dir / "otp_generation.log"
        if otp_gen_file.exists():
            with open(otp_gen_file, 'r') as f:
                for line in f:
                    timestamp, message = self.parse_log_line(line)
                    if timestamp and timestamp >= cutoff_time:
                        if "OTP_GENERATED" in message:
                            otp_stats['generated'] += 1
                        elif "OTP_CREATED" in message:
                            otp_stats['generated'] += 1
                            # Extract user type and email
                            if "User Type: live" in message:
                                otp_stats['by_user_type']['live'] += 1
                            elif "User Type: demo" in message:
                                otp_stats['by_user_type']['demo'] += 1
        
        # Analyze OTP verification logs
        otp_verify_file = self.otp_dir / "otp_verification.log"
        if otp_verify_file.exists():
            with open(otp_verify_file, 'r') as f:
                for line in f:
                    timestamp, message = self.parse_log_line(line)
                    if timestamp and timestamp >= cutoff_time:
                        if "OTP_VERIFIED" in message and "Valid: True" in message:
                            otp_stats['verified'] += 1
                            # Extract user type
                            if "User Type: live" in message:
                                otp_stats['by_user_type']['live'] += 1
                            elif "User Type: demo" in message:
                                otp_stats['by_user_type']['demo'] += 1
        
        # Analyze failed OTP attempts
        otp_failed_file = self.otp_dir / "otp_failed_attempts.log"
        if otp_failed_file.exists():
            with open(otp_failed_file, 'r') as f:
                for line in f:
                    timestamp, message = self.parse_log_line(line)
                    if timestamp and timestamp >= cutoff_time:
                        if "OTP_VERIFICATION_FAILED" in message:
                            otp_stats['failed'] += 1
        
        # Print statistics
        print(f"OTPs Generated: {otp_stats['generated']}")
        print(f"OTPs Verified: {otp_stats['verified']}")
        print(f"OTP Failures: {otp_stats['failed']}")
        
        if otp_stats['generated'] > 0:
            success_rate = (otp_stats['verified'] / otp_stats['generated']) * 100
            print(f"Success Rate: {success_rate:.1f}%")
        
        print("\nBy User Type:")
        for user_type, count in otp_stats['by_user_type'].items():
            print(f"  {user_type.capitalize()}: {count}")
    
    def analyze_email_logs(self, hours=24):
        """Analyze email sending logs."""
        print(f"\n=== Email Analysis (Last {hours} hours) ===")
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        email_stats = {
            'sent': 0,
            'failed': 0,
            'by_type': defaultdict(int),
            'by_recipient': defaultdict(int),
            'margin_calls': 0
        }
        
        # Analyze email sent logs
        email_sent_file = self.email_dir / "email_sent.log"
        if email_sent_file.exists():
            with open(email_sent_file, 'r') as f:
                for line in f:
                    timestamp, message = self.parse_log_line(line)
                    if timestamp and timestamp >= cutoff_time:
                        if "EMAIL_SENT" in message:
                            email_stats['sent'] += 1
                            
                            # Extract email type
                            type_match = re.search(r'Type: (\w+)', message)
                            if type_match:
                                email_type = type_match.group(1)
                                email_stats['by_type'][email_type] += 1
                            
                            # Extract recipient
                            recipient_match = re.search(r'To: ([^\s|]+)', message)
                            if recipient_match:
                                recipient = recipient_match.group(1)
                                email_stats['by_recipient'][recipient] += 1
        
        # Analyze email failed logs
        email_failed_file = self.email_dir / "email_failed.log"
        if email_failed_file.exists():
            with open(email_failed_file, 'r') as f:
                for line in f:
                    timestamp, message = self.parse_log_line(line)
                    if timestamp and timestamp >= cutoff_time:
                        if "EMAIL_FAILED" in message:
                            email_stats['failed'] += 1
        
        # Analyze margin call emails
        margin_call_file = self.email_dir / "email_margin_call.log"
        if margin_call_file.exists():
            with open(margin_call_file, 'r') as f:
                for line in f:
                    timestamp, message = self.parse_log_line(line)
                    if timestamp and timestamp >= cutoff_time:
                        if "MARGIN_CALL_EMAIL_SENT" in message:
                            email_stats['margin_calls'] += 1
        
        # Print statistics
        print(f"Emails Sent: {email_stats['sent']}")
        print(f"Emails Failed: {email_stats['failed']}")
        print(f"Margin Call Emails: {email_stats['margin_calls']}")
        
        if email_stats['sent'] > 0:
            success_rate = (email_stats['sent'] / (email_stats['sent'] + email_stats['failed'])) * 100
            print(f"Email Success Rate: {success_rate:.1f}%")
        
        print("\nBy Email Type:")
        for email_type, count in email_stats['by_type'].items():
            print(f"  {email_type}: {count}")
        
        print("\nTop Recipients:")
        sorted_recipients = sorted(email_stats['by_recipient'].items(), 
                                 key=lambda x: x[1], reverse=True)[:10]
        for recipient, count in sorted_recipients:
            print(f"  {recipient}: {count}")
    
    def generate_report(self, hours=24):
        """Generate a comprehensive report."""
        print(f"Log Analysis Report - Last {hours} hours")
        print("=" * 50)
        
        self.analyze_otp_logs(hours)
        self.analyze_email_logs(hours)
        
        # Check for recent errors
        print(f"\n=== Recent Errors (Last {hours} hours) ===")
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        error_files = [
            (self.otp_dir / "otp_failed_attempts.log", "OTP Failures"),
            (self.email_dir / "email_failed.log", "Email Failures")
        ]
        
        for error_file, error_type in error_files:
            if error_file.exists():
                recent_errors = []
                with open(error_file, 'r') as f:
                    for line in f:
                        timestamp, message = self.parse_log_line(line)
                        if timestamp and timestamp >= cutoff_time:
                            recent_errors.append((timestamp, message))
                
                if recent_errors:
                    print(f"\n{error_type}:")
                    for timestamp, message in recent_errors[-5:]:  # Last 5 errors
                        print(f"  {timestamp}: {message[:100]}...")

def main():
    parser = argparse.ArgumentParser(description="Analyze OTP and Email logs")
    parser.add_argument("--hours", type=int, default=24, 
                       help="Number of hours to analyze (default: 24)")
    parser.add_argument("--logs-dir", default="logs", 
                       help="Logs directory (default: logs)")
    parser.add_argument("--report", action="store_true", 
                       help="Generate comprehensive report")
    
    args = parser.parse_args()
    
    analyzer = LogAnalyzer(args.logs_dir)
    
    if args.report:
        analyzer.generate_report(args.hours)
    else:
        analyzer.analyze_otp_logs(args.hours)
        analyzer.analyze_email_logs(args.hours)

if __name__ == "__main__":
    main() 