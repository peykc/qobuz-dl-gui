import unittest

from qobuz_dl.utils import (
    format_sampling_rate_specs,
    normalize_sampling_rate_hz,
    sampling_rate_khz_for_chip,
)


class SamplingRateNormalizeTests(unittest.TestCase):
    def test_hz_unchanged(self):
        self.assertEqual(normalize_sampling_rate_hz(44100), 44100.0)
        self.assertEqual(normalize_sampling_rate_hz(96000), 96000.0)

    def test_catalog_khz(self):
        self.assertEqual(normalize_sampling_rate_hz(44.1), 44100.0)
        self.assertEqual(normalize_sampling_rate_hz(96), 96000.0)
        self.assertEqual(normalize_sampling_rate_hz(192), 192000.0)

    def test_fractional_mhz(self):
        self.assertEqual(normalize_sampling_rate_hz(0.048), 48000.0)
        self.assertEqual(normalize_sampling_rate_hz(0.0441), 44100.0)

    def test_old_half_to_one_gap(self):
        # Previously skipped (not < 0.5): must not stay as bogus Hz (~0.096 kHz).
        self.assertEqual(normalize_sampling_rate_hz(0.096), 96000.0)

    def test_chip_khz_returns_int_when_integer(self):
        self.assertEqual(sampling_rate_khz_for_chip(96000), 96)
        self.assertEqual(sampling_rate_khz_for_chip(44100), 44.1)
        self.assertEqual(sampling_rate_khz_for_chip(44.1), 44.1)

    def test_format_specs_khz_readable(self):
        s = format_sampling_rate_specs(0.048)
        self.assertIn("48000 Hz", s)
        self.assertIn("48 kHz", s)


if __name__ == "__main__":
    unittest.main()
