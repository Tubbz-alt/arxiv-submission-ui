"""Tests for :mod:`submit.controllers.classification`."""

from unittest import TestCase, mock
from werkzeug import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form
from arxiv import status
import arxiv.submission as events
from submit.controllers import classification

from pytz import timezone
from datetime import timedelta, datetime
from arxiv.users import auth, domain


class TestClassification(TestCase):
    """Test behavior of :func:`.classification` controller."""

    def setUp(self):
        """Create an authenticated session."""
        # Specify the validity period for the session.
        start = datetime.now(tz=timezone('US/Eastern'))
        end = start + timedelta(seconds=36000)
        self.session = domain.Session(
            session_id='123-session-abc',
            start_time=start, end_time=end,
            user=domain.User(
                user_id='235678',
                email='foo@foo.com',
                username='foouser',
                name=domain.UserFullName("Jane", "Bloggs", "III"),
                profile=domain.UserProfile(
                    affiliation="FSU",
                    rank=3,
                    country="de",
                    default_category=domain.Category('astro-ph', 'GA'),
                    submission_groups=['grp_physics']
                )
            ),
            authorizations=domain.Authorizations(
                scopes=[auth.scopes.CREATE_SUBMISSION,
                        auth.scopes.EDIT_SUBMISSION,
                        auth.scopes.VIEW_SUBMISSION],
                endorsements=[domain.Category('astro-ph', 'CO'),
                              domain.Category('astro-ph', 'GA')]
            )
        )

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        data, code, headers = classification.classification(
            'GET',
            MultiDict(),
            self.session,
            submission_id
        )
        self.assertEqual(code, status.HTTP_200_OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise events.exceptions.NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            classification.classification('GET', MultiDict(), self.session,
                                          submission_id)

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        data, code, headers = classification.classification(
            'POST',
            MultiDict(),
            self.session,
            submission_id
        )
        self.assertEqual(code, status.HTTP_400_BAD_REQUEST,
                         "Returns 400 bad request")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.save')
    @mock.patch('arxiv.submission.load')
    def test_post_with_invalid_category(self, mock_load, mock_save):
        """POST request with invalid category."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        mock_save.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        request_data = MultiDict({
            'category': 'astro-ph'  # <- expired
        })
        data, code, headers = classification.classification(
            'POST',
            request_data,
            self.session,
            submission_id
        )
        self.assertEqual(code, status.HTTP_400_BAD_REQUEST,
                         "Returns 400 bad request")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.save')
    @mock.patch('arxiv.submission.load')
    def test_post_with_category(self, mock_load, mock_save):
        """POST request with valid category."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        mock_save.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        request_data = MultiDict({
            'category': 'astro-ph.CO'
        })
        data, code, headers = classification.classification(
            'POST',
            request_data,
            self.session,
            submission_id
        )
        self.assertEqual(code, status.HTTP_200_OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")


class TestCrossList(TestCase):
    """Test behavior of :func:`.cross_list` controller."""

    def setUp(self):
        """Create an authenticated session."""
        # Specify the validity period for the session.
        start = datetime.now(tz=timezone('US/Eastern'))
        end = start + timedelta(seconds=36000)
        self.session = domain.Session(
            session_id='123-session-abc',
            start_time=start, end_time=end,
            user=domain.User(
                user_id='235678',
                email='foo@foo.com',
                username='foouser',
                name=domain.UserFullName("Jane", "Bloggs", "III"),
                profile=domain.UserProfile(
                    affiliation="FSU",
                    rank=3,
                    country="de",
                    default_category=domain.Category('astro-ph', 'GA'),
                    submission_groups=['grp_physics']
                )
            ),
            authorizations=domain.Authorizations(
                scopes=[auth.scopes.CREATE_SUBMISSION,
                        auth.scopes.EDIT_SUBMISSION,
                        auth.scopes.VIEW_SUBMISSION],
                endorsements=[domain.Category('astro-ph', 'CO'),
                              domain.Category('astro-ph', 'GA')]
            )
        )

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                primary_classification=mock.MagicMock(
                    category='astro-ph.EP'
                )
            ), []
        )
        data, code, headers = classification.cross_list('GET', MultiDict(), self.session,
                                                        submission_id)
        self.assertEqual(code, status.HTTP_200_OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise events.exceptions.NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            classification.cross_list(
                'GET', MultiDict(), self.session, submission_id)

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                primary_classification=mock.MagicMock(
                    category='astro-ph.EP'
                )
            ), []
        )
        data, code, headers = classification.cross_list('POST', MultiDict(), self.session,
                                                        submission_id)
        self.assertEqual(code, status.HTTP_400_BAD_REQUEST,
                         "Returns 400 bad request")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.save')
    @mock.patch('arxiv.submission.load')
    def test_post_with_invalid_category(self, mock_load, mock_save):
        """POST request with invalid category."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                primary_classification=mock.MagicMock(
                    category='astro-ph.EP'
                )
            ), []
        )
        mock_save.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                primary_classification=mock.MagicMock(
                    category='astro-ph.EP'
                )
            ), []
        )
        request_data = MultiDict({
            'category': 'astro-ph'  # <- expired
        })
        data, code, headers = classification.classification(
            'POST',
            request_data,
            self.session,
            submission_id
        )
        self.assertEqual(code, status.HTTP_400_BAD_REQUEST,
                         "Returns 400 bad request")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.save')
    @mock.patch('arxiv.submission.load')
    def test_post_with_category(self, mock_load, mock_save):
        """POST request with valid category."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                primary_classification=mock.MagicMock(
                    category='astro-ph.EP'
                )
            ), []
        )
        mock_save.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                primary_classification=mock.MagicMock(
                    category='astro-ph.EP'
                )
            ), []
        )
        request_data = MultiDict({'category': 'astro-ph.CO'})
        data, code, headers = classification.cross_list(
            'POST', request_data, self.session, submission_id)
        self.assertEqual(code, status.HTTP_200_OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")
