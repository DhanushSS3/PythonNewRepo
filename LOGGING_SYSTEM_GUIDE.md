# Specialized Logging System for OTPs and Emails

This document describes the enhanced logging system that provides separate, detailed logging for OTP (One-Time Password) operations and email communications.

## Overview

The system now includes specialized loggers that track:
- **OTP Generation**: Every OTP code generated
- **OTP Verification**: Successful and failed verification attempts
- **Email Sending**: All email operations with detailed tracking
- **Email Failures**: Failed email attempts with error details
- **Margin Call Emails**: Special tracking for margin call notifications

## Directory Structure

```
logs/
├── otps/
│   ├── otp_generation.log      # OTP generation events
│   ├── otp_verification.log    # OTP verification attempts
│   └── otp_failed_attempts.log # Failed OTP verifications
├── emails/
│   ├── email_sent.log          # Successfully sent emails
│   ├── email_failed.log        # Failed email attempts
│   └── email_margin_call.log   # Margin call emails
└── [other existing logs...]
```

## Log Formats

### OTP Generation Log
```
2024-01-01 12:00:00 - INFO - otp_generation - OTP_GENERATED - Code: 123456 - Length: 6 - Timestamp: 2024-01-01 12:00:00
2024-01-01 12:00:00 - INFO - otp_generation - OTP_CREATED - Code: 123456 - User Type: live - User ID: 123 - Expires: 2024-01-01 12:05:00 - Timestamp: 2024-01-01 12:00:00
```

### OTP Verification Log
```
2024-01-01 12:01:00 - INFO - otp_verification - OTP_VERIFIED - Code: 123456 - User Type: live - User ID: 123 - Valid: True - Timestamp: 2024-01-01 12:01:00
```

### OTP Failed Attempts Log
```
2024-01-01 12:01:00 - WARNING - otp_failed_attempts - OTP_VERIFICATION_FAILED - Code: 654321 - User Type: live - User ID: 123 - Valid: False - Timestamp: 2024-01-01 12:01:00
```

### Email Sent Log
```
2024-01-01 12:00:00 - INFO - email_sent - EMAIL_SENT - Type: signup_otp - To: user@example.com - Subject: Verify Your Email for Live Account - Timestamp: 2024-01-01 12:00:00
```

### Email Failed Log
```
2024-01-01 12:00:00 - ERROR - email_failed - EMAIL_FAILED - Type: signup_otp - To: user@example.com - Subject: Verify Your Email for Live Account - Error: SMTPAuthenticationError - Timestamp: 2024-01-01 12:00:00
```

### Margin Call Email Log
```
2024-01-01 12:00:00 - INFO - email_margin_call - MARGIN_CALL_EMAIL_SENT - To: user@example.com - Margin Level: 150% - Dashboard URL: https://dashboard.example.com - Timestamp: 2024-01-01 12:00:00
```

## Email Types Tracked

The system tracks different types of emails:

1. **signup_otp** - OTP for new user registration
2. **demo_signup_otp** - OTP for demo user registration
3. **password_reset_otp** - OTP for password reset
4. **demo_password_reset_otp** - OTP for demo user password reset
5. **margin_call** - Margin call warning emails
6. **general** - Other general emails

## Usage Examples

### Analyzing Logs

Use the provided log analyzer script:

```bash
# Analyze last 24 hours
python scripts/log_analyzer.py

# Analyze last 48 hours
python scripts/log_analyzer.py --hours 48

# Generate comprehensive report
python scripts/log_analyzer.py --report

# Analyze specific logs directory
python scripts/log_analyzer.py --logs-dir /path/to/logs
```

### Sample Output

```
=== OTP Analysis (Last 24 hours) ===
OTPs Generated: 150
OTPs Verified: 142
OTP Failures: 8
Success Rate: 94.7%

By User Type:
  Live: 120
  Demo: 30

=== Email Analysis (Last 24 hours) ===
Emails Sent: 150
Emails Failed: 2
Margin Call Emails: 5
Email Success Rate: 98.7%

By Email Type:
  signup_otp: 80
  demo_signup_otp: 30
  password_reset_otp: 35
  demo_password_reset_otp: 5

Top Recipients:
  user1@example.com: 15
  user2@example.com: 12
  user3@example.com: 8
```

## Monitoring and Alerts

### Key Metrics to Monitor

1. **OTP Success Rate**: Should be > 90%
2. **Email Success Rate**: Should be > 95%
3. **Failed OTP Attempts**: Monitor for potential security issues
4. **Email Failures**: Monitor for SMTP issues

### Alert Thresholds

- OTP Success Rate < 90%
- Email Success Rate < 95%
- More than 10 failed OTP attempts in 1 hour
- More than 5 email failures in 1 hour

## Security Considerations

### OTP Logging
- OTP codes are logged for debugging purposes
- Logs are rotated and archived
- Access to OTP logs should be restricted to authorized personnel

### Email Logging
- Email addresses are logged for tracking
- Subject lines are logged for context
- Email content is not logged for privacy

## Configuration

### Log Rotation
- Maximum file size: 10MB
- Number of backup files: 5
- Automatic rotation when size limit is reached

### Log Levels
- **Production**: INFO level for operational logs, WARNING for high-frequency logs
- **Development**: DEBUG level for detailed debugging

## Troubleshooting

### Common Issues

1. **Missing Log Files**
   - Check if log directories exist: `logs/otps/` and `logs/emails/`
   - Ensure write permissions for the application

2. **High Failure Rates**
   - Check SMTP configuration for email failures
   - Verify OTP expiration settings
   - Review network connectivity

3. **Performance Issues**
   - Monitor log file sizes
   - Check disk space
   - Review log rotation settings

### Debugging Commands

```bash
# Check log file sizes
ls -lh logs/otps/ logs/emails/

# Monitor logs in real-time
tail -f logs/otps/otp_generation.log
tail -f logs/emails/email_sent.log

# Search for specific patterns
grep "EMAIL_FAILED" logs/emails/email_failed.log
grep "OTP_VERIFICATION_FAILED" logs/otps/otp_failed_attempts.log
```

## Integration with Monitoring Systems

The log format is designed to be easily parsed by monitoring systems like:
- ELK Stack (Elasticsearch, Logstash, Kibana)
- Splunk
- Grafana
- Custom monitoring scripts

### Log Parsing Patterns

```python
# Example: Parse OTP generation log
pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - INFO - otp_generation - OTP_GENERATED - Code: (\d+) - Length: (\d+)'

# Example: Parse email sent log
pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - INFO - email_sent - EMAIL_SENT - Type: (\w+) - To: ([^\s|]+)'
```

## Best Practices

1. **Regular Monitoring**: Check logs daily for anomalies
2. **Backup Strategy**: Implement log backup and retention policies
3. **Access Control**: Restrict access to sensitive log files
4. **Performance**: Monitor log file sizes and rotation
5. **Security**: Regularly review failed attempts for security threats

## Support

For issues with the logging system:
1. Check the application logs for errors
2. Verify log directory permissions
3. Review SMTP configuration for email issues
4. Contact the development team for technical support 