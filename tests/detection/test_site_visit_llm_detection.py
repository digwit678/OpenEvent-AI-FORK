import pytest
from unittest.mock import MagicMock, patch
from detection.unified import run_unified_detection, UnifiedDetectionResult

@pytest.fixture
def mock_adapter():
    with patch("adapters.agent_adapter.get_adapter_for_provider") as mock_get:
        mock_instance = MagicMock()
        mock_get.return_value = mock_instance
        yield mock_instance

def test_site_visit_change_detection(mock_adapter):
    """Verify that site visit change messages trigger the correct signal."""
    # Mock LLM response for a site visit change
    mock_adapter.complete.return_value = """
    {
        "language": "en",
        "intent": "general_qna", 
        "signals": {
            "is_site_visit_change": true,
            "is_change_request": false
        },
        "entities": {}
    }
    """
    
    result = run_unified_detection("Can we move the tour to Tuesday?")
    
    assert result.is_site_visit_change is True
    assert result.is_change_request is False

def test_event_change_differentiation(mock_adapter):
    """Verify that event changes do NOT trigger site visit change signal."""
    # Mock LLM response for an event date change
    mock_adapter.complete.return_value = """
    {
        "language": "en",
        "intent": "edit_date", 
        "signals": {
            "is_site_visit_change": false,
            "is_change_request": true
        },
        "entities": {
            "date": "2026-05-20"
        }
    }
    """
    
    result = run_unified_detection("Can we move the event to May 20th?")
    
    assert result.is_site_visit_change is False
    assert result.is_change_request is True

def test_router_integration():
    """Verify that router uses the signal from detection result."""
    from workflows.runtime.router import _check_site_visit_intercept
    from workflows.common.types import WorkflowState
    from workflows.common.site_visit_state import set_site_visit_status
    
    # Setup state with explicit mock configuration
    state = MagicMock()
    # Configure message.body to avoid AttributeError
    state.message.body = "move the tour"
    
    event_entry = {}
    set_site_visit_status(event_entry, "scheduled")
    
    # Mock detection result in state extras
    detection = UnifiedDetectionResult(is_site_visit_change=True)
    state.extras = {"unified_detection": detection}
    
    # Mock handle_site_visit_request to return a dummy result
    with patch("workflows.runtime.router.handle_site_visit_request") as mock_handle:
        mock_handle.return_value = "handled"
        
        result = _check_site_visit_intercept(state, event_entry)
        
        assert result == "handled"
        mock_handle.assert_called_once()

def test_router_ignores_if_not_scheduled():
    """Verify that router ignores change request if site visit not scheduled."""
    from workflows.runtime.router import _check_site_visit_intercept
    from workflows.common.types import WorkflowState
    from workflows.common.site_visit_state import set_site_visit_status
    
    # Setup state with IDLE status
    state = MagicMock(spec=WorkflowState)
    event_entry = {}
    set_site_visit_status(event_entry, "idle")
    
    # Mock detection result
    detection = UnifiedDetectionResult(is_site_visit_change=True)
    state.extras = {"unified_detection": detection}
    
    result = _check_site_visit_intercept(state, event_entry)
    
    assert result is None
