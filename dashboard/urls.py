from django.urls import path
from . import views

urlpatterns = [
    # Auth Views
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),
    
    # Dashboard Views
    path('', views.overview_redirect, name='index'),
    path('overview/', views.overview_view, name='overview'),
    path('trade/', views.trade_view, name='trade'),
    path('scan/', views.scan_view, name='scan'),
    path('scan/status/', views.scan_status, name='scan_status'),
    path('history/', views.history_view, name='history'),
    path('reports/', views.reports_view, name='reports'),
    path('reports/download/<int:report_id>/', views.download_report_excel, name='download_report_excel'),
    path('alerts/', views.alerts_view, name='alerts'),
    path('performance/', views.performance_view, name='performance'),
    path('settings/', views.settings_view, name='settings'),
    path('momentum/', views.momentum_view, name='momentum'),
    path('rebalance/', views.rebalance_view, name='rebalance'),
    path('rebalance/download/', views.rebalance_download, name='rebalance_download'),
    
    # New CLI features ported to Django
    path('backtest/', views.backtest_view, name='backtest'),
    path('backtest/status/', views.backtest_status, name='backtest_status'),
    path('backtest/download-report/', views.backtest_download_report, name='backtest_download_report'),
    path('scan/custom/', views.scan_custom_view, name='scan_custom'),
    path('settings/precache/', views.settings_precache, name='settings_precache'),
    path('settings/precache/status/', views.settings_precache_status, name='settings_precache_status'),
    path('settings/clear-cache/', views.settings_clear_cache, name='settings_clear_cache'),
    path('settings/add-category/', views.settings_add_category, name='settings_add_category'),
    path('rebalance/download/<int:run_id>/', views.rebalance_download_view, name='rebalance_download_id'),
    path('portfolio/upload-transactions/', views.portfolio_upload_transactions, name='portfolio_upload_transactions'),
    path('portfolio/add-transaction/', views.add_transaction_view, name='add_transaction'),
]
