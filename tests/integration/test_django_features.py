import os
import pytest
import django

# Bootstrapping django setup first
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'momentum_project.settings')
django.setup()

from django.test import Client
from django.urls import reverse
from django.contrib.auth.models import User

@pytest.mark.django_db
class TestDjangoFeatures:
    @pytest.fixture(autouse=True)
    def setup_user(self):
        User.objects.filter(username='testuser').delete()
        User.objects.filter(username='adminuser').delete()
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.superuser = User.objects.create_superuser(username='adminuser', password='password123')
        self.client = Client()

    def test_backtest_view_redirects_anonymous(self):
        response = self.client.get(reverse('backtest'))
        assert response.status_code == 302

    def test_backtest_view_accessible_for_logged_in(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('backtest'))
        assert response.status_code == 200
        assert b"Backtest Simulation Engine" in response.content

    def test_scan_custom_view_accessible(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('scan_custom'))
        assert response.status_code == 200
        assert b"Score Custom Stock Universe" in response.content

    def test_settings_precache_blocks_normal_user(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('settings_precache'))
        assert response.status_code == 403

    def test_settings_precache_accessible_for_superuser(self):
        self.client.login(username='adminuser', password='password123')
        response = self.client.post(reverse('settings_precache'))
        # Returns 200 success because it triggers background precache thread
        assert response.status_code == 200

    def test_rebalance_view_accessible_for_logged_in(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('rebalance'))
        assert response.status_code == 200
        assert b"Portfolio Rebalance Assistant" in response.content

    def test_portfolio_upload_transactions_redirects_anonymous(self):
        response = self.client.post(reverse('portfolio_upload_transactions'))
        assert response.status_code == 302

    def test_portfolio_upload_transactions_success(self):
        self.client.login(username='testuser', password='password123')
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv_content = b"Date,Batch Type,Symbol,Price,Qty,Action\n2026-06-15,BUY,RELIANCE.NS,2500.0,10,BUY\n"
        uploaded_file = SimpleUploadedFile("transactions.csv", csv_content, content_type="text/csv")
        response = self.client.post(reverse('portfolio_upload_transactions'), {'tx_file': uploaded_file})
        assert response.status_code == 302  # Redirects to 'trade'
        
        # Verify the position is now present in the database for the test user
        from core import get_db
        DB = get_db()
        # Find user ID (Django test DB will have testuser as user id 1 since we created it in setup_user)
        # Let's check held positions for test user id
        user = User.objects.get(username='testuser')
        held = DB.held_positions(user_id=user.id)
        assert len(held) == 1
        assert held[0]["symbol"] == "RELIANCE.NS"
        assert held[0]["qty"] == 10
        assert held[0]["buy_price"] == 2500.0
        assert "2026-06-15" in held[0]["added_at"]

    def test_rebalance_download_view_unauthorized(self):
        response = self.client.get(reverse('rebalance_download_id', args=[9999]))
        assert response.status_code == 302  # Redirects anonymous to login

    def test_momentum_view_accessible_for_logged_in(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('momentum'))
        assert response.status_code == 200
        assert b"Momentum Performance Tracker" in response.content

    def test_rebalance_analysis_post_success(self):
        self.client.login(username='testuser', password='password123')
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        # Create a mock portfolio CSV file
        portfolio_content = b"Symbol,Shares,Avg_Cost\nRELIANCE.NS,10,2500.0\nTCS.NS,5,3500.0\n"
        portfolio_file = SimpleUploadedFile("portfolio.csv", portfolio_content, content_type="text/csv")
        
        # Create a mock recommendation CSV file
        reco_content = b"Symbol,WMS,PassedFilters\nRELIANCE.NS,85.5,True\nTCS.NS,45.0,True\nINFY.NS,90.0,True\n"
        reco_file = SimpleUploadedFile("recommendations.csv", reco_content, content_type="text/csv")
        
        response = self.client.post(reverse('rebalance'), {
            'use_db': 'off',
            'portfolio_file': portfolio_file,
            'reco_file': reco_file,
            'category': 'Nifty50',
            'target_size': 10
        })
        
        assert response.status_code == 200
        assert b"Rebalance Action Report" in response.content
        assert b"RELIANCE.NS" in response.content
        assert b"TCS.NS" in response.content

    def test_add_transaction_view_accessible_for_logged_in(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('add_transaction'))
        assert response.status_code == 200
        assert b"Add Transaction" in response.content
        assert b"Upload Excel/CSV" in response.content

    def test_add_transaction_view_upload_smallcase_success(self):
        self.client.login(username='testuser', password='password123')
        
        # Populate test database with an initial open position that we will partially sell
        from core import get_db
        DB = get_db()
        user = User.objects.get(username='testuser')
        
        # Pre-seed holding for KARURVYSYA.NS to test SELL realization
        DB.add_position("KARURVYSYA.NS", 250.0, 200, user_id=user.id)
        
        # Create in-memory SmallCase Excel file structure
        import pandas as pd
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        smallcase_data = [
            'Stock', 'Avg. Price (₹)', 'Qty Filled', 'Order Type', 'Details',
            'SARDAEN', 578.75, '46\xa0/\xa046', 'BUY',
            'ONGC', 286.45, '89\xa0/\xa089', 'BUY',
            'KARURVYSYA', 281.95, '107\xa0/\xa0107', 'SELL',
            'For this order your total buy value is\xa0₹ 5,13,976.87\xa0& total sell value is\xa0₹ 1,07,978.95'
        ]
        
        df = pd.DataFrame({
            'BatchManagePlaced onApr 13, 2026StatusFilled24 of 24 filled': smallcase_data
        })
        
        out = io.BytesIO()
        df.to_excel(out, index=False)
        out.seek(0)
        
        uploaded_file = SimpleUploadedFile("SmallCase.xlsx", out.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        response = self.client.post(reverse('add_transaction'), {'tx_file': uploaded_file})
        assert response.status_code == 200
        assert b"Successfully processed transaction report!" in response.content
        assert b"Applied 3 transactions" in response.content
        assert b"SARDAEN" in response.content
        assert b"ONGC" in response.content
        assert b"KARURVYSYA" in response.content
        
        # Check database to see if positions were updated correctly
        held = DB.held_positions(user_id=user.id)
        
        # We should have:
        # 1. SARDAEN.NS: Qty 46 @ 578.75
        # 2. ONGC.NS: Qty 89 @ 286.45
        # 3. KARURVYSYA.NS: Qty 200 - 107 = 93 @ 250.0 (Partial sell updates remaining qty but avg_cost stays 250)
        
        held_dict = {pos["symbol"]: pos for pos in held}
        assert len(held) == 3
        assert held_dict["SARDAEN.NS"]["qty"] == 46
        assert held_dict["SARDAEN.NS"]["buy_price"] == 578.75
        assert held_dict["ONGC.NS"]["qty"] == 89
        assert held_dict["ONGC.NS"]["buy_price"] == 286.45
        assert held_dict["KARURVYSYA.NS"]["qty"] == 93
        assert held_dict["KARURVYSYA.NS"]["buy_price"] == 250.0
        
        # Check closed trades for the realized sell trade
        closed = DB.closed_positions(user_id=user.id)
        assert len(closed) == 1
        assert closed[0]["symbol"] == "KARURVYSYA.NS"
        assert closed[0]["qty"] == 107
        assert closed[0]["buy_price"] == 250.0
        assert closed[0]["sell_price"] == 281.95
        assert closed[0]["pnl"] == (281.95 - 250.0) * 107




