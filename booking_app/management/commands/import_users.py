import csv
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils.crypto import get_random_string

User = get_user_model()


class Command(BaseCommand):
    help = 'Imports users from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='The path to the CSV file to import')

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']

        if not os.path.exists(csv_file_path):
            self.stdout.write(self.style.ERROR(f'File not found: {csv_file_path}'))
            return

        self.stdout.write(f"Importing users from {csv_file_path}...")

        created_count = 0
        updated_count = 0
        errors = []

        # Use 'utf-8-sig' to automatically handle the Excel BOM (\ufeff)
        try:
            with open(csv_file_path, 'r', encoding='utf-8-sig') as f:
                # --- 1. Sniff the delimiter (Comma vs Semicolon) ---
                sample = f.read(1024)
                f.seek(0)  # Go back to start
                try:
                    dialect = csv.Sniffer().sniff(sample)
                    delimiter = dialect.delimiter
                except csv.Error:
                    # Fallback if sniffing fails
                    delimiter = ','

                self.stdout.write(f"Detected delimiter: '{delimiter}'")

                # --- 2. Read the CSV ---
                reader = csv.DictReader(f, delimiter=delimiter)

                # Normalize headers: lower-case and strip spaces (e.g., " Email " -> "email")
                if reader.fieldnames:
                    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]

                # Check required headers
                required_headers = ['username', 'email']
                missing_headers = [h for h in required_headers if h not in reader.fieldnames]

                if missing_headers:
                    self.stdout.write(self.style.ERROR(f"CSV missing headers: {', '.join(missing_headers)}"))
                    self.stdout.write(f"Found headers: {reader.fieldnames}")
                    return

                # --- 3. Process Rows ---
                with transaction.atomic():
                    for i, row in enumerate(reader, start=2):
                        username = row.get('username', '').strip()
                        email = row.get('email', '').strip()
                        first_name = row.get('first_name', '').strip()
                        last_name = row.get('last_name', '').strip()
                        phone_number = row.get('phone_number', '').strip()

                        # Handle groups column
                        group_names = []
                        if row.get('groups'):
                            # Split by comma if multiple groups
                            group_names = [g.strip() for g in row.get('groups').split(',') if g.strip()]

                        if not username or not email:
                            errors.append(f"Row {i}: Skipped - Missing username or email.")
                            continue

                        # Create or Update User
                        user, created = User.objects.update_or_create(
                            username=username,
                            defaults={
                                'email': email,
                                'first_name': first_name,
                                'last_name': last_name,
                                'phone_number': phone_number,
                                'is_active': True,
                            }
                        )

                        if created:
                            # Set a random temporary password and force change
                            temp_password = get_random_string(12)
                            user.set_password(temp_password)
                            user.requires_password_change = True
                            user.save()
                            created_count += 1
                            self.stdout.write(f"Created: {username}")
                        else:
                            updated_count += 1
                            # self.stdout.write(f"Updated: {username}")

                        # Assign Groups
                        if group_names:
                            for g_name in group_names:
                                try:
                                    group = Group.objects.get(name__iexact=g_name)
                                    user.groups.add(group)
                                except Group.DoesNotExist:
                                    self.stdout.write(
                                        self.style.WARNING(f"  - Warning (Row {i}): Group '{g_name}' does not exist."))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An unexpected error occurred: {e}"))
            return

        # Summary
        if errors:
            self.stdout.write(self.style.ERROR("\nErrors encountered:"))
            for err in errors:
                self.stdout.write(self.style.ERROR(err))

        self.stdout.write(self.style.SUCCESS(f"\nImport Finished! Created: {created_count}, Updated: {updated_count}"))