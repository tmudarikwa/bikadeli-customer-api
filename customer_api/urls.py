from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.health import liveness_view, readiness_view
from core.views import check_delivery_zone
from core.views.profile import ProfileViewSet
from core.views.referrals import apply_referral_code, referral_data, referral_list
from core.views.subscriptions import cancel_subscription, subscribe, subscription_plans, subscription_status
from core.wallet_views import WalletViewSet
from customers import urls as customer_urls
from orders import urls as order_urls
from payments.views import PaymentViewSet
from pricing.views import delivery_fee_estimate
from vendors.marketplace_views import MarketplaceCategoryViewSet, MarketplaceProductViewSet

profile_router = DefaultRouter()
profile_router.register('profile', ProfileViewSet, basename='customer-profile')

payment_router = DefaultRouter()
payment_router.register('transactions', PaymentViewSet, basename='customer-payments')

wallet_router = DefaultRouter()
wallet_router.register('wallet', WalletViewSet, basename='customer-wallet')

marketplace_router = DefaultRouter()
marketplace_router.register('marketplace/products', MarketplaceProductViewSet, basename='marketplace-products')
marketplace_router.register('marketplace/categories', MarketplaceCategoryViewSet, basename='marketplace-categories')

urlpatterns = [
    path('health/', liveness_view, name='health-liveness'),
    path('health/ready/', readiness_view, name='health-readiness'),
    path('api/v1/customers/', include(customer_urls.urlpatterns)),
    path('api/v1/orders/', include(order_urls.urlpatterns)),
    path('api/v1/payments/', include(payment_router.urls)),
    path('api/v1/', include(wallet_router.urls)),
    path('api/v1/', include(marketplace_router.urls)),
    path('api/v1/', include(profile_router.urls)),
    path('api/v1/delivery-zones/check/', check_delivery_zone, name='customer-delivery-zone-check'),
    path('api/v1/pricing/estimate/', delivery_fee_estimate, name='customer-delivery-fee-estimate'),
    path('api/v1/auth/referral/', referral_data, name='customer-referral-data'),
    path('api/v1/auth/referral/list/', referral_list, name='customer-referral-list'),
    path('api/v1/auth/referral/apply/', apply_referral_code, name='customer-referral-apply'),
    path('api/v1/subscription/plans/', subscription_plans, name='customer-subscription-plans'),
    path('api/v1/subscription/status/', subscription_status, name='customer-subscription-status'),
    path('api/v1/subscription/subscribe/', subscribe, name='customer-subscription-subscribe'),
    path('api/v1/subscription/cancel/', cancel_subscription, name='customer-subscription-cancel'),
]
