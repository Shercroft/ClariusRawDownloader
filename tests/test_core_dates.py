from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import clarius_downloader_core as core


class SyncDateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.old_range_start = core.PATIENT_RANGE_START
        self.old_range_end = core.PATIENT_RANGE_END
        self.old_force_range = core.FORCE_PATIENT_RANGE
        core.PATIENT_RANGE_START = None
        core.PATIENT_RANGE_END = None
        core.FORCE_PATIENT_RANGE = False

    def tearDown(self):
        core.PATIENT_RANGE_START = self.old_range_start
        core.PATIENT_RANGE_END = self.old_range_end
        core.FORCE_PATIENT_RANGE = self.old_force_range

    def test_unknown_date_is_not_automatically_new(self):
        record = {
            "patient_id": "REB16236_180_TR_02",
            "upload_dt": None,
            "exam_date_dt": None,
            "nested_date_dt": None,
            "nested_date_score": None,
        }
        self.assertFalse(core.exam_is_new_enough(record, datetime(2026, 8, 1)))

    def test_low_confidence_created_nested_date_is_not_sync_date(self):
        # created_at/uploaded_at must not decide the clinical sync boundary.
        record = {
            "patient_id": "REB16236_180_TR_02",
            "exam_date_dt": None,
            "nested_date_dt": datetime(2026, 8, 28, 12, 30),
            "nested_date_score": 80,
            "nested_date_path": "created_at",
        }
        self.assertIsNone(core._trusted_nested_sync_date(record))
        self.assertFalse(core.exam_is_new_enough(record, datetime(2026, 8, 1)))

    def test_trusted_new_clinical_nested_date_is_new(self):
        record = {
            "patient_id": "REB16236_254_TR_02",
            "exam_date_dt": None,
            "nested_date_dt": datetime(2026, 8, 12, 10, 2),
            "nested_date_score": 120,
            "nested_date_path": "exam_date",
        }
        self.assertTrue(core.exam_is_new_enough(record, datetime(2026, 8, 1)))

    def test_live_page_clock_conflicting_with_old_clinical_json_is_rejected(self):
        record = {
            "nested_date_dt": datetime(2026, 6, 10, 8, 38),
            "nested_date_score": 120,
            "nested_date_path": "exam_date",
        }
        self.assertTrue(
            core._detail_date_conflicts_with_trusted_json(datetime.now(), record)
        )

    def test_capture_date_requires_clinical_confidence(self):
        dt = datetime(2026, 6, 10)
        self.assertIsNone(core._trusted_capture_sync_date(dt, 80))
        self.assertEqual(core._trusted_capture_sync_date(dt, 115), dt)


class CloudExamDateRegressionTests(unittest.TestCase):
    """Regression tests for the Aug-28 folder-name bug seen on P403/P247."""

    def setUp(self):
        self.old_debug = core.DEBUG_DATE_RESOLUTION
        core.DEBUG_DATE_RESOLUTION = False

    def tearDown(self):
        core.DEBUG_DATE_RESOLUTION = self.old_debug

    def test_two_digit_cloud_date_parses(self):
        self.assertEqual(
            core.try_parse_date("8/21/26, 7:37 AM"),
            datetime(2026, 8, 21, 7, 37),
        )
        self.assertEqual(
            core.try_parse_date("8/6/26, 7:58 AM"),
            datetime(2026, 8, 6, 7, 58),
        )

    def test_api_upload_date_is_not_treated_as_exam_date(self):
        record = core.normalize_exam_object(
            {
                "id": 3462376,
                "patient_msp": "REB16236_403_TL_02",
                "uploaded_at": "2026-08-28T12:33:00",
                "status": "Completed",
            }
        )
        self.assertEqual(record["upload_dt"], datetime(2026, 8, 28, 12, 33))
        self.assertIsNone(record["exam_date_dt"])

    def test_top_level_exam_date_wins_over_later_upload_date(self):
        record = core.normalize_exam_object(
            {
                "id": 3462376,
                "patient_msp": "REB16236_403_TL_02",
                "exam_date": "2026-08-21T07:37:00",
                "uploaded_at": "2026-08-28T12:33:00",
            }
        )
        self.assertEqual(record["exam_date_dt"], datetime(2026, 8, 21, 7, 37))
        sync_dt, _ = core.choose_sync_date(record)
        folder_dt, _ = core.choose_folder_date(record)
        self.assertEqual(sync_dt, datetime(2026, 8, 21, 7, 37))
        self.assertEqual(folder_dt, datetime(2026, 8, 21, 7, 37))
        self.assertEqual(
            core.build_study_folder(record["patient_id"], folder_dt),
            "P403_TL_02_Aug_21-26-REB16236-403",
        )

    def test_p247_cloud_exam_date_controls_folder_not_download_day(self):
        record = {
            "patient_id": "REB16236_247_TR_02",
            "exam_date_dt": datetime(2026, 8, 6, 7, 58),
            "exam_date_source": "Clarius Cloud Exam Date",
            "upload_dt": datetime(2026, 8, 28, 12, 39),
            "nested_date_dt": datetime(2026, 8, 28, 12, 39),
            "nested_date_score": 80,
        }
        folder_dt, source = core.choose_folder_date(record)
        self.assertEqual(folder_dt, datetime(2026, 8, 6, 7, 58))
        self.assertEqual(source, "Clarius Cloud Exam Date")
        self.assertEqual(
            core.build_study_folder(record["patient_id"], folder_dt),
            "P247_TR_02_Aug_06-26-REB16236-247",
        )

    def test_later_upload_cannot_make_old_exam_new(self):
        record = {
            "patient_id": "REB16236_247_TR_02",
            "exam_date_dt": datetime(2026, 8, 6, 7, 58),
            "exam_date_source": "Clarius Cloud Exam Date",
            "upload_dt": datetime(2026, 8, 28, 12, 39),
            "nested_date_dt": datetime(2026, 8, 28, 12, 39),
            "nested_date_score": 80,
        }
        self.assertFalse(core.exam_is_new_enough(record, datetime(2026, 8, 10)))
        self.assertTrue(core.exam_is_new_enough(record, datetime(2026, 8, 1)))

    def test_upload_only_never_controls_folder_name(self):
        record = {
            "patient_id": "REB16236_403_TL_02",
            "exam_date_dt": None,
            "upload_dt": datetime(2026, 8, 28, 12, 33),
            "nested_date_dt": datetime(2026, 8, 28, 12, 33),
            "nested_date_score": 80,
        }
        folder_dt, source = core.choose_folder_date(record)
        self.assertIsNone(folder_dt)
        self.assertIsNone(source)
        self.assertEqual(
            core.build_study_folder(record["patient_id"], folder_dt),
            "P403_TL_02_UNKDATE-REB16236-403",
        )

    def test_capture_acquisition_date_can_be_safe_folder_fallback(self):
        record = {
            "patient_id": "REB16236_247_TR_02",
            "exam_date_dt": None,
            "upload_dt": datetime(2026, 8, 28, 12, 39),
            "nested_date_dt": datetime(2026, 8, 28, 12, 39),
            "nested_date_score": 80,
        }
        folder_dt, source = core.choose_folder_date(
            record,
            capture_date_dt=datetime(2026, 8, 6, 7, 58),
            capture_score=115,
        )
        self.assertEqual(folder_dt, datetime(2026, 8, 6, 7, 58))
        self.assertEqual(source, "capture acquisition metadata")

    def test_existing_upload_timestamp_does_not_skip_detail_exam_date_lookup(self):
        record = {
            "patient_id": "REB16236_403_TL_02",
            "exam_id": 3462376,
            "exam_date_dt": None,
            "upload_dt": datetime(2026, 8, 28, 12, 33),
            "detail_url": None,
        }

        def fake_direct(_page, current):
            current = dict(current)
            current["exam_date_dt"] = datetime(2026, 8, 21, 7, 37)
            current["exam_date_source"] = "Clarius Cloud Exam Date"
            return current

        with patch.object(core, "hydrate_api_record_from_direct_detail_page", side_effect=fake_direct) as mocked:
            hydrated = core.hydrate_missing_api_date_from_html(object(), record)

        mocked.assert_called_once()
        self.assertEqual(hydrated["exam_date_dt"], datetime(2026, 8, 21, 7, 37))


class ExistingFolderRepairTests(unittest.TestCase):
    def test_p403_wrong_aug28_folder_is_renamed_to_cloud_aug21(self):
        with tempfile.TemporaryDirectory() as root:
            wrong = Path(root) / "P403_TL_02_Aug_28-26-REB16236-403"
            wrong.mkdir()
            (wrong / "keep_me.txt").write_text("existing data", encoding="utf-8")

            with patch.object(core, "log"):
                result = core.get_or_create_study_path(
                    root,
                    "REB16236_403_TL_02",
                    datetime(2026, 8, 21, 7, 37),
                )

            expected = Path(root) / "P403_TL_02_Aug_21-26-REB16236-403"
            self.assertEqual(Path(result), expected)
            self.assertTrue(expected.is_dir())
            self.assertTrue((expected / "keep_me.txt").is_file())
            self.assertFalse(wrong.exists())

    def test_p247_wrong_aug28_folder_is_renamed_to_cloud_aug06(self):
        with tempfile.TemporaryDirectory() as root:
            wrong = Path(root) / "P247_TR_02_Aug_28-26-REB16236-247"
            wrong.mkdir()

            with patch.object(core, "log"):
                result = core.get_or_create_study_path(
                    root,
                    "REB16236_247_TR_02",
                    datetime(2026, 8, 6, 7, 58),
                )

            expected = Path(root) / "P247_TR_02_Aug_06-26-REB16236-247"
            self.assertEqual(Path(result), expected)
            self.assertTrue(expected.is_dir())
            self.assertFalse(wrong.exists())

    def test_multiple_mismatched_folders_are_never_guessed(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "P403_TL_02_Aug_28-26-REB16236-403").mkdir()
            (Path(root) / "P403_TL_02_UNKDATE-REB16236-403").mkdir()

            with patch.object(core, "log"):
                with self.assertRaises(RuntimeError):
                    core.get_or_create_study_path(
                        root,
                        "REB16236_403_TL_02",
                        datetime(2026, 8, 21, 7, 37),
                    )


class DetailPageScopingRegressionTests(unittest.TestCase):
    def test_exam_id_in_query_is_not_treated_as_exam_specific_path(self):
        self.assertFalse(
            core._url_path_contains_exam_id(
                "https://cloud.clarius.com/10870/exams/?exam_id=3462376",
                3462376,
            )
        )

    def test_exam_id_in_detail_path_is_specific(self):
        self.assertTrue(
            core._url_path_contains_exam_id(
                "https://cloud.clarius.com/10870/exams/3462376/",
                3462376,
            )
        )

    def test_patient_scoped_text_reads_only_labelled_exam_date(self):
        text = """
        REB16236_247_TR_02
        Abdomen
        Exam Date
        8/6/26, 7:58 AM
        Uploaded
        8/28/26, 12:40 PM
        """
        self.assertEqual(
            core._extract_labeled_date_from_text(text, ["Exam Date", "Acquired Date"]),
            datetime(2026, 8, 6, 7, 58),
        )
        self.assertEqual(
            core._extract_labeled_date_from_text(text, ["Uploaded", "Upload Date"]),
            datetime(2026, 8, 28, 12, 40),
        )

    def test_same_line_exam_date_parses(self):
        text = "REB16236_403_TL_02\nExam Date: 8/21/26, 7:37 AM\n"
        self.assertEqual(
            core._extract_labeled_date_from_text(text, ["Exam Date"]),
            datetime(2026, 8, 21, 7, 37),
        )



class StartDateTimeCanonicalRegressionTests(unittest.TestCase):
    """Real log regressions: API start_datetime must beat locale-scraped detail text."""

    def setUp(self):
        self.old_debug = core.DEBUG_DATE_RESOLUTION
        core.DEBUG_DATE_RESOLUTION = False

    def tearDown(self):
        core.DEBUG_DATE_RESOLUTION = self.old_debug

    def _record(self, patient_id, exam_id, raw_start):
        return core.normalize_exam_object({
            "id": exam_id,
            "patient_msp": patient_id,
            "status": "Completed",
            "start_datetime": raw_start,
        })

    def test_p254_start_datetime_matches_cloud_aug12(self):
        record = self._record(
            "REB16236_254_TR_02", 3432883, "2026-08-12T14:02:01.197000Z"
        )
        self.assertEqual(record["exam_date_dt"].date(), datetime(2026, 8, 12).date())
        self.assertEqual(record["exam_date_key"], "start_datetime")
        folder_dt, _ = core.choose_folder_date(record)
        self.assertEqual(
            core.build_study_folder(record["patient_id"], folder_dt),
            "P254_TR_02_Aug_12-26-REB16236-254",
        )

    def test_p247_start_datetime_matches_cloud_aug06(self):
        record = self._record(
            "REB16236_247_TR_02", 3415272, "2026-08-06T11:58:55.613000Z"
        )
        self.assertEqual(record["exam_date_dt"].date(), datetime(2026, 8, 6).date())
        folder_dt, _ = core.choose_folder_date(record)
        self.assertEqual(
            core.build_study_folder(record["patient_id"], folder_dt),
            "P247_TR_02_Aug_06-26-REB16236-247",
        )

    def test_p403_start_datetime_matches_cloud_aug21(self):
        record = self._record(
            "REB16236_403_TL_02", 3462376, "2026-08-21T11:37:30.648000Z"
        )
        self.assertEqual(record["exam_date_dt"].date(), datetime(2026, 8, 21).date())
        folder_dt, _ = core.choose_folder_date(record)
        self.assertEqual(
            core.build_study_folder(record["patient_id"], folder_dt),
            "P403_TL_02_Aug_21-26-REB16236-403",
        )

    def test_p184_start_datetime_matches_cloud_aug06_not_june08(self):
        record = self._record(
            "REB16236_184_TR_02", 3415269, "2026-08-06T14:43:00Z"
        )
        self.assertEqual(record["exam_date_dt"].date(), datetime(2026, 8, 6).date())

    def test_start_datetime_is_high_confidence_nested_date(self):
        dt, path, raw, score = core.best_date_from_json({
            "metadata": {"start_datetime": "2026-08-12T14:02:01.197000Z"}
        })
        self.assertEqual(dt.date(), datetime(2026, 8, 12).date())
        self.assertIn("start_datetime", path)
        self.assertGreaterEqual(score, core.MIN_SYNC_DATE_FALLBACK_SCORE)


if __name__ == "__main__":
    unittest.main()


class NumericDateLocaleRegressionTests(unittest.TestCase):
    """Regression tests for Aug 12 being misread as Dec 8."""

    def test_cloud_numeric_dates_are_mdy(self):
        self.assertEqual(
            core.try_parse_date("8/12/26, 10:02 AM"),
            datetime(2026, 8, 12, 10, 2),
        )

    def test_future_swapped_date_is_rejected(self):
        reference = datetime(2026, 8, 28, 14, 0)
        self.assertTrue(
            core._plausible_clinical_date(
                datetime(2026, 8, 12, 10, 2), reference_dt=reference
            )
        )
        self.assertFalse(
            core._plausible_clinical_date(
                datetime(2026, 12, 8, 10, 2), reference_dt=reference
            )
        )

    def test_browser_locale_is_fixed_to_us(self):
        self.assertEqual(core.CLOUD_BROWSER_LOCALE, "en-US")
