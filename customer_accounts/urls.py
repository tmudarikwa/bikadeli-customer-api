from django.urls import path

from . import views
from .loyalty import (
    LoyaltyBalanceView,
    LoyaltyTransactionHistoryView,
    OrderLoyaltyAwardCallbackView,
    RedeemLoyaltyPointsView,
)

app_name = 'customer_accounts'

urlpatterns = [
    path('api/v1/profile/me/', views.profile_me_view, name='customer-profile-me'),
    path('api/v1/customers/loyalty/', LoyaltyBalanceView.as_view(), name='loyalty-balance-legacy'),
    path('api/v1/customers/loyalty/balance/', LoyaltyBalanceView.as_view(), name='loyalty-balance'),
    path(
        'api/v1/customers/loyalty/transactions/',
        LoyaltyTransactionHistoryView.as_view(),
        name='loyalty-transaction-history',
    ),
    path('api/v1/customers/loyalty/redeem/', RedeemLoyaltyPointsView.as_view(), name='loyalty-redeem'),
    path('internal/v1/customers/loyalty/orders/award/', OrderLoyaltyAwardCallbackView.as_view(), name='loyalty-order-award'),
    path('api/v1/customers/support-tickets/', views.support_tickets_view, name='support-ticket-list-create'),
    path(
        'api/v1/customers/support-tickets/<int:pk>/messages/',
        views.ticket_messages_view,
        name='support-ticket-messages',
    ),
    path(
        'api/v1/customers/support-tickets/<int:pk>/reply/',
        views.ticket_reply_view,
        name='support-ticket-reply',
    ),
    path('api/v1/customers/addresses/', views.CustomerAddressListCreateView.as_view(), name='address-list'),
    path(
        'api/v1/customers/addresses/default/',
        views.CustomerDefaultAddressView.as_view(),
        name='address-default',
    ),
    path(
        'api/v1/customers/addresses/<int:pk>/',
        views.CustomerAddressDetailView.as_view(),
        name='address-detail',
    ),
    path(
        'api/v1/customers/addresses/<int:pk>/set_default/',
        views.CustomerSetDefaultAddressView.as_view(),
        name='address-set-default',
    ),
    path(
        'api/v1/customers/vendor-favourites/',
        views.CustomerVendorFavouritesView.as_view(),
        name='vendor-favourites',
    ),
    path(
        'api/v1/customers/favourites/',
        views.CustomerProductFavouritesView.as_view(),
        name='product-favourites',
    ),
]
