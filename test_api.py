import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

class TestGrainflowControlTower(unittest.TestCase):

    def test_health_check(self):
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "OPERATIONAL")

    def test_list_grain_lots(self):
        response = client.get("/api/v1/lots/")
        self.assertEqual(response.status_code, 200)
        lots = response.json()
        self.assertIsInstance(lots, list)
        self.assertGreaterEqual(len(lots), 5)

    def test_create_grain_lot(self):
        payload = {
            "cluster_id": "GROBOGAN-01",
            "gapoktan_name": "Gapoktan Sidomulyo",
            "farmer_name": "Pak Joko",
            "farmer_phone": "+6281299887766",
            "gross_weight_kg": 6000.0,
            "moisture_pct": 33.5,
            "damaged_kernels_pct": 7.0,
            "base_price_per_kg": 5800.0,
            "quality_premium_per_kg": 0.0,
            "harvest_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        response = client.post("/api/v1/lots/", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["aflatoxin_risk_level"], "CRITICAL")
        self.assertIn("LOT-GROB-", data["id"])
        self.assertEqual(data["net_payout_amount"], 34800000.0)

    def test_settle_payout(self):
        # Settle lot 3
        response = client.post("/api/v1/lots/LOT-GROB-20261108-003/settle")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["settlement_status"], "DISBURSED")
        self.assertEqual(data["dso_days"], 0.0)

    def test_dryer_capacity_and_stress_test(self):
        # List dryers
        dryers_res = client.get("/api/v1/capacity/dryers")
        self.assertEqual(dryers_res.status_code, 200)
        dryers = dryers_res.json()
        self.assertGreaterEqual(len(dryers), 3)

        # Capacity stress test
        stress_res = client.get("/api/v1/capacity/stress-test?forecast_days=14&forecast_daily_harvest_tons=65.0")
        self.assertEqual(stress_res.status_code, 200)
        stress_data = stress_res.json()
        self.assertIn("capacity_status", stress_data)
        self.assertIn(stress_data["capacity_status"], ["NORMAL", "STRESSED", "CRITICAL"])

    def test_storage_telemetry_and_critical_spike(self):
        # Test normal telemetry
        normal_payload = {
            "stack_code": "STACK-TEST-01",
            "temperature_c": 28.0,
            "humidity_rh_pct": 60.0,
            "temp_slope_1h": 0.1
        }
        res_normal = client.post("/api/v1/storage/telemetry", json=normal_payload)
        self.assertEqual(res_normal.status_code, 200)
        self.assertEqual(res_normal.json()["status"], "NORMAL")
        self.assertFalse(res_normal.json()["alert_triggered"])

        # Test critical heat spike trigger (Temp > 35.0, Slope > 0.5, RH > 70.0)
        spike_payload = {
            "stack_code": "STACK-TEST-01",
            "temperature_c": 36.5,
            "humidity_rh_pct": 74.0,
            "temp_slope_1h": 0.75
        }
        res_spike = client.post("/api/v1/storage/telemetry", json=spike_payload)
        self.assertEqual(res_spike.status_code, 200)
        spike_data = res_spike.json()
        self.assertEqual(spike_data["status"], "CRITICAL_HEAT_SPIKE")
        self.assertTrue(spike_data["alert_triggered"])

    def test_dml_metrics(self):
        res = client.get("/api/v1/storage/dml-metrics")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreater(data["total_monitored_tonnage"], 0)
        self.assertGreater(data["monetary_value_saved_idr"], 0)

    def test_shift_action_logs_and_acknowledge(self):
        logs_res = client.get("/api/v1/logs/")
        self.assertEqual(logs_res.status_code, 200)
        logs = logs_res.json()
        self.assertGreaterEqual(len(logs), 1)

        first_log_id = logs[0]["id"]
        ack_res = client.post(f"/api/v1/logs/{first_log_id}/acknowledge")
        self.assertEqual(ack_res.status_code, 200)
        self.assertTrue(ack_res.json()["acknowledged"])


if __name__ == "__main__":
    unittest.main()

