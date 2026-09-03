from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/today/", views.today),
    path("api/demo/scan/", views.demo_scan),
    path("api/scan/", views.real_scan),
    path("api/chart/<str:symbol>/", views.chart),
    path("api/scanner/", views.scanner_list),
    path("api/market-ticker/", views.market_ticker),
    path("api/live-prices/", views.live_prices),
    path("api/demo-account/", views.demo_account),
    path("api/demo-account/config/", views.demo_account_config),
    path("api/demo-buy/<int:plan_id>/", views.demo_buy),
    path("api/demo-close/<int:position_id>/", views.demo_close),
    path("api/plans/<int:plan_id>/insight/", views.plan_insight),
    path("api/system/", views.system_status),
    path("api/predictions/", views.prediction_history),
    path("api/intraday/<str:symbol>/", views.intraday),
]
