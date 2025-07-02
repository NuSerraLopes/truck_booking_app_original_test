# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\utils.py

from datetime import timedelta, date

def add_business_days(start_date, num_business_days):
    """
    Adds a specified number of business days (excluding weekends) to a start date.
    Args:
        start_date (datetime.date): The date from which to start counting.
        num_business_days (int): The number of business days to add.
    Returns:
        datetime.date: The calculated date after adding business days.
    """
    current_date = start_date
    days_added = 0
    while days_added < num_business_days:
        current_date += timedelta(days=1)
        # weekday() returns 0 for Monday, 1 for Tuesday, ..., 5 for Saturday, 6 for Sunday
        if current_date.weekday() < 5:  # Check if it's a weekday (Monday-Friday)
            days_added += 1
    return current_date