import logging

import httpx
from bikadeli_common.authentication import AccessTokenAuthentication
from django.conf import settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger(__name__)

_TILE_URL = "https://mt1.google.com/vt/"


def _is_customer(request):
    return bool(
        request.user
        and request.user.is_authenticated
        and request.auth
        and request.auth.get("user_type") == "CUSTOMER"
    )


def _validate_guest_token(token):
    if not settings.ORDERS_SERVICE_URL:
        return Response(
            {"detail": "Orders service is not configured."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
        with httpx.Client(
            timeout=settings.UPSTREAM_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            response = client.get(
                f"{settings.ORDERS_SERVICE_URL}/api/v1/orders/guest-token/validate/",
                params={"guest_token": token},
            )
    except httpx.RequestError as exc:
        logger.warning("Guest map-token validation failed: %s", type(exc).__name__)
        return Response(
            {"detail": "Orders service is unavailable."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if response.status_code == 204:
        return True
    if response.status_code == status.HTTP_404_NOT_FOUND:
        return False
    logger.warning(
        "Guest map-token validation returned status %s", response.status_code
    )
    return Response(
        {"detail": "Orders service is unavailable."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _fetch_tile(z, x, y):
    try:
        z, x, y = int(z), int(x), int(y)
    except (TypeError, ValueError):
        return HttpResponse("Invalid tile coordinates", status=400)
    if not 0 <= z <= 22 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
        return HttpResponse("Invalid tile coordinates", status=400)
    if not settings.GOOGLE_MAPS_API_KEY:
        return HttpResponse("Map tiles not configured", status=503)

    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.get(
                _TILE_URL,
                params={
                    "lyrs": "m",
                    "x": x,
                    "y": y,
                    "z": z,
                    "key": settings.GOOGLE_MAPS_API_KEY,
                },
                headers={"User-Agent": "ZimDelivery/1.0"},
            )
    except httpx.RequestError as exc:
        logger.error(
            "Map tile proxy failed z=%s x=%s y=%s: %s", z, x, y, type(exc).__name__
        )
        return HttpResponse("Tile fetch failed", status=502)

    if response.status_code != status.HTTP_200_OK or not response.headers.get(
        "content-type", ""
    ).startswith("image/"):
        logger.warning("Map tile provider returned status %s", response.status_code)
        return HttpResponse("Tile fetch failed", status=502)
    return HttpResponse(
        response.content,
        content_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@api_view(["GET"])
@authentication_classes([AccessTokenAuthentication])
@permission_classes([AllowAny])
def customer_map_tile(request, z, x, y):
    if not _is_customer(request):
        token = request.query_params.get("guest_token", "") or request.headers.get(
            "X-Guest-Token", ""
        )
        if not token or len(token) > 64:
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
        token_is_valid = _validate_guest_token(token)
        if isinstance(token_is_valid, Response):
            return token_is_valid
        if not token_is_valid:
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
    return _fetch_tile(z, x, y)
