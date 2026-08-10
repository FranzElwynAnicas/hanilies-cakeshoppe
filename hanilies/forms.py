import calendar
from datetime import timedelta

from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.utils import timezone


MINIMUM_BOOKING_MESSAGE = 'Orders must be placed at least 3 days before the pickup, delivery, or event date.'
INVALID_BOOKING_WINDOW_MESSAGE = 'Please select a valid date within the allowed booking window.'
CAKE_MAX_BOOKING_MESSAGE = 'Cake orders can only be booked up to 30 days in advance.'
PACKAGE_MAX_BOOKING_MESSAGE = 'Package orders can only be booked up to 30 days in advance.'
BOOKING_FULL_MESSAGE = 'This date is already fully booked. Please choose another date.'
CAKE_BOOKING_FULL_MESSAGE = 'This date already has the maximum 10 cake orders. Please choose another date.'
PACKAGE_BOOKING_FULL_MESSAGE = 'This date already has the maximum 2 package/event bookings. Please choose another date.'
BOOKING_BLOCKED_MESSAGE = 'This date is unavailable for bookings. Please choose another date.'

ORDER_MIN_LEAD_DAYS = 3
ORDER_MAX_LEAD_DAYS = 30
CAKE_DAILY_ORDER_LIMIT = 10
PACKAGE_DAILY_EVENT_LIMIT = 2
ORDER_DAILY_BOOKING_LIMIT = CAKE_DAILY_ORDER_LIMIT + PACKAGE_DAILY_EVENT_LIMIT
CAKE_ORDER_MIN_LEAD_DAYS = ORDER_MIN_LEAD_DAYS
CAKE_ORDER_MAX_LEAD_DAYS = ORDER_MAX_LEAD_DAYS
PACKAGE_ORDER_MIN_LEAD_DAYS = ORDER_MIN_LEAD_DAYS
PACKAGE_ORDER_MAX_LEAD_DAYS = ORDER_MAX_LEAD_DAYS
ACTIVE_BOOKING_STATUSES = [
    'pending',
    'payment_retry',
    'confirmed',
    'preparing',
    'ready_for_pickup',
    'out_for_delivery',
]


def add_calendar_months(base_date, months):
    target_month_index = base_date.month - 1 + months
    target_year = base_date.year + (target_month_index // 12)
    target_month = (target_month_index % 12) + 1
    target_day = min(base_date.day, calendar.monthrange(
        target_year, target_month)[1])
    return base_date.replace(year=target_year, month=target_month, day=target_day)


def build_cake_booking_window(today=None):
    current_date = today or timezone.now().date()
    earliest_date = current_date + timedelta(days=CAKE_ORDER_MIN_LEAD_DAYS)
    latest_date = current_date + timedelta(days=CAKE_ORDER_MAX_LEAD_DAYS)
    return {
        'min': earliest_date.isoformat(),
        'max': latest_date.isoformat(),
        'earliest_date': earliest_date,
        'latest_date': latest_date,
    }


def build_package_booking_window(today=None):
    current_date = today or timezone.now().date()
    earliest_date = current_date + timedelta(days=PACKAGE_ORDER_MIN_LEAD_DAYS)
    latest_date = current_date + timedelta(days=PACKAGE_ORDER_MAX_LEAD_DAYS)
    return {
        'min': earliest_date.isoformat(),
        'max': latest_date.isoformat(),
        'earliest_date': earliest_date,
        'latest_date': latest_date,
    }


def get_booking_date_availability(selected_date, order_type='all'):
    from .models import BookingCalendarBlock, CakeOrder, PackageOrder

    normalized_order_type = (order_type or 'all').strip().lower()
    if normalized_order_type not in {'cake', 'package', 'all'}:
        normalized_order_type = 'all'

    blocked_date = BookingCalendarBlock.objects.filter(
        date=selected_date).first()
    cake_count = CakeOrder.objects.filter(
        delivery_date__date=selected_date,
        order_status__in=ACTIVE_BOOKING_STATUSES,
        is_archived=False,
    ).count()
    package_count = PackageOrder.objects.filter(
        event_date=selected_date,
        order_status__in=ACTIVE_BOOKING_STATUSES,
        is_archived=False,
    ).count()
    total_booking_count = cake_count + package_count
    cake_remaining_slots = max(CAKE_DAILY_ORDER_LIMIT - cake_count, 0)
    package_remaining_slots = max(PACKAGE_DAILY_EVENT_LIMIT - package_count, 0)

    if normalized_order_type == 'cake':
        booking_count = cake_count
        capacity = CAKE_DAILY_ORDER_LIMIT
        remaining_slots = cake_remaining_slots
        full_message = CAKE_BOOKING_FULL_MESSAGE
        available_by_capacity = cake_count < CAKE_DAILY_ORDER_LIMIT
        available_message = f'This date is available for cake orders. {cake_remaining_slots} of {CAKE_DAILY_ORDER_LIMIT} cake slots remain.'
    elif normalized_order_type == 'package':
        booking_count = package_count
        capacity = PACKAGE_DAILY_EVENT_LIMIT
        remaining_slots = package_remaining_slots
        full_message = PACKAGE_BOOKING_FULL_MESSAGE
        available_by_capacity = package_count < PACKAGE_DAILY_EVENT_LIMIT
        available_message = f'This date is available for event packages. {package_remaining_slots} of {PACKAGE_DAILY_EVENT_LIMIT} package slots remain.'
    else:
        booking_count = total_booking_count
        capacity = ORDER_DAILY_BOOKING_LIMIT
        remaining_slots = cake_remaining_slots + package_remaining_slots
        full_message = BOOKING_FULL_MESSAGE
        available_by_capacity = cake_count < CAKE_DAILY_ORDER_LIMIT or package_count < PACKAGE_DAILY_EVENT_LIMIT
        available_message = f'This date has {cake_remaining_slots} cake slots and {package_remaining_slots} package/event slots remaining.'

    payload = {
        'booking_count': booking_count,
        'remaining_slots': remaining_slots,
        'capacity': capacity,
        'cake_count': cake_count,
        'cake_capacity': CAKE_DAILY_ORDER_LIMIT,
        'cake_remaining_slots': cake_remaining_slots,
        'cake_available': cake_count < CAKE_DAILY_ORDER_LIMIT,
        'package_count': package_count,
        'package_capacity': PACKAGE_DAILY_EVENT_LIMIT,
        'package_remaining_slots': package_remaining_slots,
        'package_available': package_count < PACKAGE_DAILY_EVENT_LIMIT,
        'total_booking_count': total_booking_count,
        'total_capacity': ORDER_DAILY_BOOKING_LIMIT,
    }

    if blocked_date:
        return {
            **payload,
            'available': False,
            'message': blocked_date.reason or BOOKING_BLOCKED_MESSAGE,
            'blocked': True,
        }

    if not available_by_capacity:
        return {
            **payload,
            'available': False,
            'message': full_message,
            'remaining_slots': 0,
            'blocked': False,
        }

    return {
        **payload,
        'available': True,
        'message': f'{available_message} Please log in or continue checkout to reserve it.',
        'blocked': False,
    }


class BaseBookingDateForm(forms.Form):
    date_field_name = ''
    too_late_message = INVALID_BOOKING_WINDOW_MESSAGE
    order_type = 'all'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        booking_window = self.get_booking_window()
        self.fields[self.date_field_name].widget.attrs.update({
            'min': booking_window['min'],
            'max': booking_window['max'],
        })

    def get_booking_window(self):
        raise NotImplementedError

    def clean(self):
        cleaned_data = super().clean()
        selected_date = cleaned_data.get(self.date_field_name)
        if not selected_date:
            return cleaned_data

        booking_window = self.get_booking_window()
        if selected_date < booking_window['earliest_date']:
            raise ValidationError(MINIMUM_BOOKING_MESSAGE)
        if selected_date > booking_window['latest_date']:
            raise ValidationError(self.too_late_message)

        availability = get_booking_date_availability(
            selected_date, self.order_type)
        if not availability['available']:
            raise ValidationError(availability['message'])

        return cleaned_data


class CakeBookingDateForm(BaseBookingDateForm):
    date_field_name = 'delivery_date'
    too_late_message = CAKE_MAX_BOOKING_MESSAGE
    order_type = 'cake'
    delivery_date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type': 'date'}),
        error_messages={
            'required': INVALID_BOOKING_WINDOW_MESSAGE,
            'invalid': INVALID_BOOKING_WINDOW_MESSAGE,
        },
    )

    def get_booking_window(self):
        return build_cake_booking_window()


class PackageBookingDateForm(BaseBookingDateForm):
    date_field_name = 'event_date'
    too_late_message = PACKAGE_MAX_BOOKING_MESSAGE
    order_type = 'package'
    event_date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type': 'date'}),
        error_messages={
            'required': INVALID_BOOKING_WINDOW_MESSAGE,
            'invalid': INVALID_BOOKING_WINDOW_MESSAGE,
        },
    )

    def get_booking_window(self):
        return build_package_booking_window()


class HaniliesPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].label = 'Email address'
        self.fields['email'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Enter your registered email address',
            'autocomplete': 'email',
        })


class HaniliesSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].label = 'New password'
        self.fields['new_password2'].label = 'Confirm password'
        self.fields['new_password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Enter your new password',
            'autocomplete': 'new-password',
        })
        self.fields['new_password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirm your new password',
            'autocomplete': 'new-password',
        })


class ContactInquiryForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your full name',
            'autocomplete': 'name',
        }),
    )
    contact_detail = forms.CharField(
        max_length=150,
        label='Email or Contact Number',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email or mobile number',
            'autocomplete': 'email',
        }),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Tell us how we can help you.',
            'rows': 6,
        }),
    )

    def clean_contact_detail(self):
        value = (self.cleaned_data.get('contact_detail') or '').strip()
        if len(value) < 6:
            raise ValidationError(
                'Please enter a valid email address or contact number.')
        return value

    def clean_message(self):
        value = (self.cleaned_data.get('message') or '').strip()
        if len(value) < 10:
            raise ValidationError(
                'Please enter a longer message so we can help you properly.')
        return value


class AdminContactInquiryReplyForm(forms.Form):
    reply_message = forms.CharField(
        label='Reply Message',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Write the response you want to send to the customer.',
            'rows': 6,
        }),
    )

    def clean_reply_message(self):
        value = (self.cleaned_data.get('reply_message') or '').strip()
        if len(value) < 5:
            raise ValidationError(
                'Please write a longer reply before sending.')
        return value
