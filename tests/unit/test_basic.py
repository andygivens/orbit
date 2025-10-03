"""
Simple test to verify pytest is working correctly.
"""

from datetime import datetime

import pytest


def test_basic_functionality():
    """Test that basic Python functionality works"""
    assert 1 + 1 == 2
    assert "hello" == "hello"
    assert len([1, 2, 3]) == 3


def test_datetime_operations():
    """Test datetime operations"""
    now = datetime.now()
    assert isinstance(now, datetime)
    assert now.year >= 2025


class TestBasicClass:
    """Test class-based test structure"""

    def test_method_one(self):
        """Test method in class"""
        data = {"key": "value"}
        assert data["key"] == "value"

    def test_method_two(self):
        """Another test method"""
        items = [1, 2, 3, 4, 5]
        assert sum(items) == 15


@pytest.mark.unit
def test_with_marker():
    """Test with unit marker"""
    assert True


def test_simple_mock():
    """Test that pytest-mock is available"""
    from unittest.mock import Mock
    mock_obj = Mock()
    mock_obj.method.return_value = "mocked"
    assert mock_obj.method() == "mocked"


@pytest.mark.asyncio
async def test_async_function():
    """Test async functionality"""
    async def async_add(a, b):
        return a + b

    result = await async_add(2, 3)
    assert result == 5
