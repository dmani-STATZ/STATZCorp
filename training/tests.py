from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from .models import Course, Account, Matrix, UserAccount, Tracker
from .forms import CmmcDocumentUploadForm
from .views import admin_cmmc_upload
import tempfile
import os


class CmmcDocumentUploadFormTest(TestCase):
    """Test cases for CmmcDocumentUploadForm validation."""
    
    def setUp(self):
        """Set up test data."""
        # Create test users
        self.user1 = User.objects.create_user(
            username='testuser1',
            email='test1@example.com',
            password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='testpass123'
        )
        
        # Create test course
        self.course = Course.objects.create(
            name='Test CMMC Course',
            description='A test course for CMMC compliance'
        )
        
        # Create test account
        self.account = Account.objects.create(
            type='cui_user',
            description='CUI User account type'
        )
        
        # Create matrix entry linking course to account
        self.matrix = Matrix.objects.create(
            course=self.course,
            account=self.account,
            frequency='annually'
        )
        
        # Link user1 to the account (user2 is not linked)
        UserAccount.objects.create(user=self.user1, account=self.account)
    
    def test_valid_user_course_combination(self):
        """Test form validation with valid user/course combination."""
        form_data = {
            'user': self.user1.id,
            'course': self.course.id,
        }
        form = CmmcDocumentUploadForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_invalid_user_course_combination(self):
        """Test form validation with invalid user/course combination."""
        form_data = {
            'user': self.user2.id,  # user2 is not linked to any account
            'course': self.course.id,
        }
        form = CmmcDocumentUploadForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('not required to complete', str(form.errors))
    
    def test_form_fields_present(self):
        """Test that all required form fields are present."""
        form = CmmcDocumentUploadForm()
        self.assertIn('user', form.fields)
        self.assertIn('course', form.fields)
        self.assertIn('file', form.fields)
    
    def test_user_queryset_filtered_to_active(self):
        """Test that user queryset only includes active users."""
        # Create an inactive user
        inactive_user = User.objects.create_user(
            username='inactive',
            email='inactive@example.com',
            password='testpass123',
            is_active=False
        )
        
        form = CmmcDocumentUploadForm()
        user_queryset = form.fields['user'].queryset
        self.assertNotIn(inactive_user, user_queryset)
        self.assertIn(self.user1, user_queryset)


class AdminCmmcUploadViewTest(TestCase):
    """Test cases for admin_cmmc_upload view."""
    
    def setUp(self):
        """Set up test data."""
        # Create staff user
        self.staff_user = User.objects.create_user(
            username='staff',
            email='staff@example.com',
            password='testpass123',
            is_staff=True
        )
        
        # Create regular user
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='testpass123',
            is_staff=False
        )
        
        # Create test user for uploads
        self.test_user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test data
        self.course = Course.objects.create(
            name='Test CMMC Course',
            description='A test course for CMMC compliance'
        )
        
        self.account = Account.objects.create(
            type='cui_user',
            description='CUI User account type'
        )
        
        self.matrix = Matrix.objects.create(
            course=self.course,
            account=self.account,
            frequency='annually'
        )
        
        UserAccount.objects.create(user=self.test_user, account=self.account)
        
        self.client = Client()
    
    def test_staff_access_allowed(self):
        """Test that staff users can access the view."""
        self.client.login(username='staff', password='testpass123')
        response = self.client.get(reverse('training:admin_cmmc_upload'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'CMMC Document Upload')
    
    def test_non_staff_access_denied(self):
        """Test that non-staff users are denied access."""
        self.client.login(username='regular', password='testpass123')
        response = self.client.get(reverse('training:admin_cmmc_upload'))
        self.assertEqual(response.status_code, 302)  # Redirect
        self.assertRedirects(response, reverse('training:dashboard'))
    
    def test_anonymous_access_denied(self):
        """Test that anonymous users are denied access."""
        response = self.client.get(reverse('training:admin_cmmc_upload'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_successful_document_upload(self):
        """Test successful document upload creates Tracker record."""
        self.client.login(username='staff', password='testpass123')
        
        # Create a test file
        test_file = SimpleUploadedFile(
            "test_document.pdf",
            b"file_content",
            content_type="application/pdf"
        )
        
        form_data = {
            'user': self.test_user.id,
            'course': self.course.id,
            'file': test_file
        }
        
        response = self.client.post(reverse('training:admin_cmmc_upload'), form_data)
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Check that Tracker record was created
        tracker = Tracker.objects.filter(
            user=self.test_user,
            matrix=self.matrix
        ).first()
        
        self.assertIsNotNone(tracker)
        self.assertIsNotNone(tracker.document)
        self.assertEqual(tracker.document_name, 'test_document.pdf')
        self.assertEqual(tracker.completed_date, timezone.now().date())
    
    def test_upload_updates_existing_tracker(self):
        """Test that uploading for existing tracker updates the record."""
        self.client.login(username='staff', password='testpass123')
        
        # Create existing tracker record
        existing_tracker = Tracker.objects.create(
            user=self.test_user,
            matrix=self.matrix,
            completed_date=timezone.now().date()
        )
        
        # Upload new document
        test_file = SimpleUploadedFile(
            "new_document.pdf",
            b"new_file_content",
            content_type="application/pdf"
        )
        
        form_data = {
            'user': self.test_user.id,
            'course': self.course.id,
            'file': test_file
        }
        
        response = self.client.post(reverse('training:admin_cmmc_upload'), form_data)
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Check that existing tracker was updated
        existing_tracker.refresh_from_db()
        self.assertIsNotNone(existing_tracker.document)
        self.assertEqual(existing_tracker.document_name, 'new_document.pdf')
        
        # Should still be only one tracker record
        tracker_count = Tracker.objects.filter(
            user=self.test_user,
            matrix=self.matrix
        ).count()
        self.assertEqual(tracker_count, 1)
    
    def test_invalid_user_course_combination_error(self):
        """Test error handling for invalid user/course combination."""
        self.client.login(username='staff', password='testpass123')
        
        # Create user not linked to any account
        unlinked_user = User.objects.create_user(
            username='unlinked',
            email='unlinked@example.com',
            password='testpass123'
        )
        
        test_file = SimpleUploadedFile(
            "test_document.pdf",
            b"file_content",
            content_type="application/pdf"
        )
        
        form_data = {
            'user': unlinked_user.id,
            'course': self.course.id,
            'file': test_file
        }
        
        response = self.client.post(reverse('training:admin_cmmc_upload'), form_data)
        
        # Should return form with errors
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No valid matrix entry found')
    
    def test_form_validation_errors(self):
        """Test form validation error handling."""
        self.client.login(username='staff', password='testpass123')
        
        # Submit form without required fields
        form_data = {}
        response = self.client.post(reverse('training:admin_cmmc_upload'), form_data)
        
        # Should return form with errors
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
    
    def test_context_includes_existing_uploads(self):
        """Test that context includes recent uploads."""
        self.client.login(username='staff', password='testpass123')
        
        # Create some existing tracker records with documents
        tracker1 = Tracker.objects.create(
            user=self.test_user,
            matrix=self.matrix,
            completed_date=timezone.now().date(),
            document=b"test_content_1",
            document_name="test1.pdf"
        )
        
        response = self.client.get(reverse('training:admin_cmmc_upload'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('existing_uploads', response.context)
        self.assertIn(tracker1, response.context['existing_uploads'])


class CmmcDocumentUploadIntegrationTest(TestCase):
    """Integration tests for the complete CMMC document upload workflow."""
    
    def setUp(self):
        """Set up comprehensive test data."""
        # Create staff user
        self.staff_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='testpass123',
            is_staff=True,
            first_name='Admin',
            last_name='User'
        )
        
        # Create test users with different account types
        self.cui_user = User.objects.create_user(
            username='cui_user',
            email='cui@example.com',
            password='testpass123',
            first_name='CUI',
            last_name='User'
        )
        
        self.non_cui_user = User.objects.create_user(
            username='non_cui_user',
            email='noncui@example.com',
            password='testpass123',
            first_name='Non-CUI',
            last_name='User'
        )
        
        # Create courses
        self.cmmc_course1 = Course.objects.create(
            name='CMMC Security Awareness',
            description='Basic security awareness training'
        )
        
        self.cmmc_course2 = Course.objects.create(
            name='CMMC Data Handling',
            description='Data handling procedures training'
        )
        
        self.regular_course = Course.objects.create(
            name='General Training',
            description='Non-CMMC training'
        )
        
        # Create account types
        self.cui_account = Account.objects.create(
            type='cui_user',
            description='CUI User account type'
        )
        
        self.non_cui_account = Account.objects.create(
            type='non_cui_user',
            description='Non-CUI User account type'
        )
        
        # Create matrix entries
        Matrix.objects.create(
            course=self.cmmc_course1,
            account=self.cui_account,
            frequency='annually'
        )
        
        Matrix.objects.create(
            course=self.cmmc_course2,
            account=self.cui_account,
            frequency='bi-annually'
        )
        
        Matrix.objects.create(
            course=self.regular_course,
            account=self.non_cui_account,
            frequency='once'
        )
        
        # Link users to accounts
        UserAccount.objects.create(user=self.cui_user, account=self.cui_account)
        UserAccount.objects.create(user=self.non_cui_user, account=self.non_cui_account)
        
        self.client = Client()
    
    def test_complete_workflow_cui_user_cmmc_course(self):
        """Test complete workflow for CUI user with CMMC course."""
        self.client.login(username='admin', password='testpass123')
        
        # Upload document for CUI user with CMMC course
        test_file = SimpleUploadedFile(
            "security_certificate.pdf",
            b"certificate_content",
            content_type="application/pdf"
        )
        
        form_data = {
            'user': self.cui_user.id,
            'course': self.cmmc_course1.id,
            'file': test_file
        }
        
        response = self.client.post(reverse('training:admin_cmmc_upload'), form_data)
        
        # Should succeed
        self.assertEqual(response.status_code, 302)
        
        # Verify tracker record
        tracker = Tracker.objects.get(user=self.cui_user, matrix__course=self.cmmc_course1)
        self.assertIsNotNone(tracker.document)
        self.assertEqual(tracker.document_name, 'security_certificate.pdf')
        self.assertEqual(tracker.completed_date, timezone.now().date())
    
    def test_workflow_rejects_invalid_combinations(self):
        """Test that workflow rejects invalid user/course combinations."""
        self.client.login(username='admin', password='testpass123')
        
        # Try to upload CMMC course for non-CUI user
        test_file = SimpleUploadedFile(
            "invalid_cert.pdf",
            b"cert_content",
            content_type="application/pdf"
        )
        
        form_data = {
            'user': self.non_cui_user.id,
            'course': self.cmmc_course1.id,  # CMMC course for non-CUI user
            'file': test_file
        }
        
        response = self.client.post(reverse('training:admin_cmmc_upload'), form_data)
        
        # Should fail with error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No valid matrix entry found')
    
    def test_multiple_uploads_same_user_course(self):
        """Test multiple uploads for same user/course combination."""
        self.client.login(username='admin', password='testpass123')
        
        # First upload
        test_file1 = SimpleUploadedFile(
            "first_cert.pdf",
            b"first_content",
            content_type="application/pdf"
        )
        
        form_data1 = {
            'user': self.cui_user.id,
            'course': self.cmmc_course1.id,
            'file': test_file1
        }
        
        response1 = self.client.post(reverse('training:admin_cmmc_upload'), form_data1)
        self.assertEqual(response1.status_code, 302)
        
        # Second upload (should update existing)
        test_file2 = SimpleUploadedFile(
            "updated_cert.pdf",
            b"updated_content",
            content_type="application/pdf"
        )
        
        form_data2 = {
            'user': self.cui_user.id,
            'course': self.cmmc_course1.id,
            'file': test_file2
        }
        
        response2 = self.client.post(reverse('training:admin_cmmc_upload'), form_data2)
        self.assertEqual(response2.status_code, 302)
        
        # Verify only one tracker record exists and it has the latest document
        tracker_count = Tracker.objects.filter(
            user=self.cui_user,
            matrix__course=self.cmmc_course1
        ).count()
        self.assertEqual(tracker_count, 1)
        
        tracker = Tracker.objects.get(user=self.cui_user, matrix__course=self.cmmc_course1)
        self.assertEqual(tracker.document_name, 'updated_cert.pdf')


class MarkCompleteRecertifyTest(TestCase):
    """Tests for mark_complete initial completion and recertification flows."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="recert_user",
            email="recert@example.com",
            password="testpass123",
        )
        self.account = Account.objects.create(
            type="cui_user",
            description="CUI User account type",
        )
        UserAccount.objects.create(user=self.user, account=self.account)
        self.client.login(username="recert_user", password="testpass123")

    def _create_course_and_matrix(self, upload=False, frequency="annually"):
        course = Course.objects.create(
            name="Recert Test Course",
            description="Course for recertification tests",
            upload=upload,
        )
        matrix = Matrix.objects.create(
            course=course,
            account=self.account,
            frequency=frequency,
        )
        return course, matrix

    def test_early_recertify_while_still_current(self):
        """Recertifying while training is still valid creates a new row and shows recertified message."""
        course, matrix = self._create_course_and_matrix()
        prior_date = timezone.now().date() - timezone.timedelta(days=30)
        Tracker.objects.create(
            user=self.user,
            matrix=matrix,
            completed_date=prior_date,
        )

        response = self.client.post(
            reverse("training:mark_complete", kwargs={"course_id": course.id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(
            response,
            reverse("training:user_requirements"),
            fetch_redirect_response=False,
        )

        today = timezone.now().date()
        trackers = Tracker.objects.filter(user=self.user, matrix=matrix).order_by(
            "-completed_date"
        )
        self.assertEqual(trackers.count(), 2)
        self.assertEqual(trackers.first().completed_date, today)

        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(
            any("recertified" in msg.lower() for msg in messages),
            msg=f"Expected recertified message, got: {messages}",
        )

    def test_upload_document_recertifies_existing_completion(self):
        """Upload recertification for cert-required course preserves the prior Tracker document."""
        course, matrix = self._create_course_and_matrix(upload=True)
        prior_date = timezone.now().date() - timezone.timedelta(days=90)
        old_tracker = Tracker.objects.create(
            user=self.user,
            matrix=matrix,
            completed_date=prior_date,
            document=b"original_cert_bytes",
            document_name="original_cert.pdf",
        )

        test_file = SimpleUploadedFile(
            "new_cert.pdf",
            b"new_cert_bytes",
            content_type="application/pdf",
        )
        response = self.client.post(
            reverse("training:upload_document", kwargs={"matrix_id": matrix.id}),
            {"document": test_file},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        old_tracker.refresh_from_db()
        self.assertEqual(old_tracker.document, b"original_cert_bytes")
        self.assertEqual(old_tracker.document_name, "original_cert.pdf")

        today = timezone.now().date()
        trackers = Tracker.objects.filter(user=self.user, matrix=matrix).order_by(
            "-completed_date", "-id"
        )
        self.assertEqual(trackers.count(), 2)
        latest = trackers.first()
        self.assertEqual(latest.completed_date, today)
        self.assertNotEqual(latest.id, old_tracker.id)
        self.assertEqual(latest.document, b"new_cert_bytes")
        self.assertEqual(latest.document_name, "new_cert.pdf")

        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(
            any("recertified" in msg.lower() for msg in messages),
            msg=f"Expected recertified message, got: {messages}",
        )

    def test_upload_document_creates_tracker_for_new_completion(self):
        """Upload with no prior Tracker creates today's row with document attached."""
        course, matrix = self._create_course_and_matrix(upload=True)
        self.assertFalse(
            Tracker.objects.filter(user=self.user, matrix=matrix).exists()
        )

        test_file = SimpleUploadedFile(
            "first_cert.pdf",
            b"first_cert_bytes",
            content_type="application/pdf",
        )
        response = self.client.post(
            reverse("training:upload_document", kwargs={"matrix_id": matrix.id}),
            {"document": test_file},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        tracker = Tracker.objects.get(user=self.user, matrix=matrix)
        self.assertEqual(tracker.completed_date, timezone.now().date())
        self.assertEqual(tracker.document, b"first_cert_bytes")
        self.assertEqual(tracker.document_name, "first_cert.pdf")

        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(
            any("marked as completed" in msg.lower() for msg in messages),
            msg=f"Expected completion message, got: {messages}",
        )

    def test_mark_complete_rejects_cert_required_course(self):
        """mark_complete is blocked for courses that require certificate upload."""
        course, matrix = self._create_course_and_matrix(upload=True)

        response = self.client.post(
            reverse("training:mark_complete", kwargs={"course_id": course.id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Tracker.objects.filter(user=self.user, matrix=matrix).exists()
        )

        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(
            any("certificate upload" in msg.lower() for msg in messages),
            msg=f"Expected rejection message, got: {messages}",
        )

    def test_mark_complete_still_works_for_non_cert_course(self):
        """Non-cert courses still recertify via mark_complete without upload."""
        course, matrix = self._create_course_and_matrix(upload=False)
        prior_date = timezone.now().date() - timezone.timedelta(days=45)
        Tracker.objects.create(
            user=self.user,
            matrix=matrix,
            completed_date=prior_date,
        )

        response = self.client.post(
            reverse("training:mark_complete", kwargs={"course_id": course.id}),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Tracker.objects.filter(user=self.user, matrix=matrix).count(), 2
        )

        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(
            any("recertified" in msg.lower() for msg in messages),
            msg=f"Expected recertified message, got: {messages}",
        )

    def test_same_day_recertify_does_not_duplicate_tracker(self):
        """Clicking recertify twice on the same day does not create a duplicate Tracker row."""
        course, matrix = self._create_course_and_matrix()
        prior_date = timezone.now().date() - timezone.timedelta(days=60)
        Tracker.objects.create(
            user=self.user,
            matrix=matrix,
            completed_date=prior_date,
        )

        url = reverse("training:mark_complete", kwargs={"course_id": course.id})
        self.client.post(url)
        count_after_first = Tracker.objects.filter(
            user=self.user,
            matrix=matrix,
            completed_date=timezone.now().date(),
        ).count()
        self.assertEqual(count_after_first, 1)

        response = self.client.post(url, follow=True)
        count_after_second = Tracker.objects.filter(
            user=self.user,
            matrix=matrix,
            completed_date=timezone.now().date(),
        ).count()
        self.assertEqual(count_after_second, 1)

        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(
            any("already recertified today" in msg.lower() for msg in messages),
            msg=f"Expected same-day info message, got: {messages}",
        )
