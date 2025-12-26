"""
Tests for startup validation (PR4).

Verifies:
- Startup fails when expected prompts are missing
- PROMPT_BUNDLE_HASH changes when prompt content changes
- validate_template_coverage() catches missing field templates
- Health endpoint returns build info
"""

from pathlib import Path
from unittest.mock import patch


class TestStartupValidation:
    """Tests for startup validation behavior."""

    def test_validate_template_coverage_returns_valid_structure(self):
        """Verify validate_template_coverage returns expected structure."""
        from app.plan_graph import validate_template_coverage

        result = validate_template_coverage()

        assert "valid" in result
        assert "missing_fields" in result
        assert "insufficient_suggestions" in result
        assert "errors" in result
        assert isinstance(result["valid"], bool)
        assert isinstance(result["missing_fields"], list)
        assert isinstance(result["insufficient_suggestions"], dict)
        assert isinstance(result["errors"], list)

    def test_validate_template_coverage_passes_with_current_templates(self):
        """Current templates should pass validation."""
        from app.plan_graph import validate_template_coverage

        result = validate_template_coverage()

        # Should be valid with current templates
        assert result["valid"] is True
        assert result["missing_fields"] == []

    def test_validate_template_coverage_detects_missing_field(self):
        """Validation should fail when a core field template is missing."""
        from app.plan_graph import validate_template_coverage

        # Mock _load_required_fields_templates to return incomplete data
        incomplete_templates = {
            "dates": {
                "questions": ["When do you want to travel?"],
                "suggestions": {"default": ["Next week", "Next month", "Summer"]},
            },
            "origin": {
                "questions": ["Where will you be traveling from?"],
                "suggestions": {"default": ["New York", "London", "Tokyo"]},
            },
            # Missing: destinations, travelers, budget
        }

        with patch(
            "app.plan_graph._load_required_fields_templates",
            return_value=incomplete_templates,
        ):
            result = validate_template_coverage()

        # Should be invalid - missing fields
        assert result["valid"] is False
        assert len(result["missing_fields"]) > 0
        assert "destinations" in result["missing_fields"]


class TestPromptBundleHash:
    """Tests for PROMPT_BUNDLE_HASH computation and stability."""

    def test_prompt_bundle_hash_is_stable(self):
        """PROMPT_BUNDLE_HASH should be deterministic."""
        from app.plan_graph import PROMPT_BUNDLE_HASH, _compute_prompt_bundle_hash

        # Compute twice - should be identical
        hash1 = _compute_prompt_bundle_hash()
        hash2 = _compute_prompt_bundle_hash()

        assert hash1 == hash2
        assert hash1 == PROMPT_BUNDLE_HASH

    def test_prompt_bundle_hash_is_16_chars(self):
        """PROMPT_BUNDLE_HASH should be 16 character hex string."""
        from app.plan_graph import PROMPT_BUNDLE_HASH

        assert len(PROMPT_BUNDLE_HASH) == 16
        # Should be valid hex
        int(PROMPT_BUNDLE_HASH, 16)

    def test_prompt_bundle_hash_changes_on_content_change(self):
        """PROMPT_BUNDLE_HASH should change when prompt file content changes."""
        from app.plan_graph import _compute_prompt_bundle_hash

        original_hash = _compute_prompt_bundle_hash()

        # Mock Path.read_bytes to return different content
        original_read_bytes = Path.read_bytes

        def mock_read_bytes(self):
            content = original_read_bytes(self)
            if "required_fields.txt" in str(self):
                # Append some content to change hash
                return content + b"\n# Modified for test"
            return content

        with patch.object(Path, "read_bytes", mock_read_bytes):
            modified_hash = _compute_prompt_bundle_hash()

        # Hash should be different
        assert original_hash != modified_hash

    def test_prompt_bundle_hash_normalizes_line_endings(self):
        """PROMPT_BUNDLE_HASH should produce same hash regardless of CRLF vs LF."""
        # This is tested implicitly by the hash function normalization
        # The _compute_prompt_bundle_hash converts CRLF to LF
        from app.plan_graph import _compute_prompt_bundle_hash

        original_read_bytes = Path.read_bytes

        def mock_crlf_read_bytes(self):
            content = original_read_bytes(self)
            # Convert to CRLF
            return content.replace(b"\n", b"\r\n")

        def mock_lf_read_bytes(self):
            content = original_read_bytes(self)
            # Ensure LF only
            return content.replace(b"\r\n", b"\n")

        with patch.object(Path, "read_bytes", mock_crlf_read_bytes):
            crlf_hash = _compute_prompt_bundle_hash()

        with patch.object(Path, "read_bytes", mock_lf_read_bytes):
            lf_hash = _compute_prompt_bundle_hash()

        # Should be identical after normalization
        assert crlf_hash == lf_hash


class TestHealthEndpoint:
    """Tests for health endpoint build info."""

    def test_health_endpoint_returns_build_info(self):
        """Health endpoint should include prompt_bundle_hash and build info."""
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        # Check required fields
        assert "status" in data
        assert data["status"] == "ok"
        assert "prompt_bundle_hash" in data
        assert "planner_build_id" in data
        assert "cache_schema_version" in data

        # Validate format
        assert len(data["prompt_bundle_hash"]) == 16
        assert isinstance(data["cache_schema_version"], int)


class TestBuildIdentifiers:
    """Tests for build identifier constants."""

    def test_planner_build_id_exists(self):
        """PLANNER_BUILD_ID should be defined."""
        from app.plan_graph import PLANNER_BUILD_ID

        assert PLANNER_BUILD_ID is not None
        assert len(PLANNER_BUILD_ID) <= 12  # Truncated to 12 chars

    def test_cache_schema_version_is_integer(self):
        """CACHE_SCHEMA_VERSION should be a positive integer."""
        from app.plan_graph import CACHE_SCHEMA_VERSION

        assert isinstance(CACHE_SCHEMA_VERSION, int)
        assert CACHE_SCHEMA_VERSION >= 1


class TestStartupFailFast:
    """Tests for startup fail-fast behavior."""

    def test_startup_with_invalid_templates_raises(self):
        """
        Startup should raise RuntimeError when template validation fails.

        Note: This test simulates the lifespan behavior without actually
        running the full FastAPI lifespan context.
        """
        from app.plan_graph import validate_template_coverage

        # Create an incomplete template that would fail validation
        incomplete_templates = {
            # Only partial templates - missing core fields
            "dates": {
                "questions": ["When?"],
                "suggestions": {"default": ["Soon"]},
            },
        }

        with patch(
            "app.plan_graph._load_required_fields_templates",
            return_value=incomplete_templates,
        ):
            result = validate_template_coverage()

        # Verify this would trigger the fail-fast path
        assert result["valid"] is False
        assert len(result["missing_fields"]) > 0

        # The actual RuntimeError is raised in lifespan() based on this result
        # We don't test the full lifespan here to avoid side effects


class TestExpectedPromptFiles:
    """Tests for expected prompt file existence."""

    def test_critical_prompt_files_exist(self):
        """All critical prompt files should exist."""
        prompt_dir = Path(__file__).parent.parent / "app" / "prompts"

        critical_prompts = [
            "strategy_pre_core.txt",
            "extractor_light.txt",
            "extractor.txt",
            "required_fields.txt",
            "required_fields_confirm.txt",
            "router.txt",
        ]

        for prompt_file in critical_prompts:
            prompt_path = prompt_dir / prompt_file
            assert prompt_path.exists(), f"Critical prompt file missing: {prompt_file}"

    def test_required_fields_templates_json_exists(self):
        """required_fields_templates.json should exist."""
        prompt_dir = Path(__file__).parent.parent / "app" / "prompts"
        templates_path = prompt_dir / "required_fields_templates.json"

        assert templates_path.exists(), "required_fields_templates.json missing"

    def test_required_fields_templates_json_is_valid(self):
        """required_fields_templates.json should be valid JSON."""
        import json

        prompt_dir = Path(__file__).parent.parent / "app" / "prompts"
        templates_path = prompt_dir / "required_fields_templates.json"

        with open(templates_path) as f:
            data = json.load(f)

        # Should have required keys
        assert "dates" in data
        assert "destinations" in data
        assert "origin" in data
        assert "travelers" in data
        assert "budget" in data
