import os
import tempfile

# Must be set before `app` is imported so the engine points to a temp database.
_tmpdir = tempfile.mkdtemp(prefix="simple_forms_test_")
os.environ["SIMPLE_FORMS_DB"] = os.path.join(_tmpdir, "test.db")
# The app refuses to start with the default admin password.
os.environ["SIMPLE_FORMS_ADMIN_PASSWORD"] = "test-admin-password"
