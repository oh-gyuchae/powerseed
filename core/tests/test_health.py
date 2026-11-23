from django.test import SimpleTestCase, override_settings


class HealthCheckTests(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=["example.com"], SECURE_SSL_REDIRECT=True)
    def test_answers_before_host_and_https_checks(self):
        response = self.client.get("/healthz", headers={"host": "10.0.0.1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
