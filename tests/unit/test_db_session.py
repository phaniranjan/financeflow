from unittest.mock import MagicMock, patch

import pytest

from financeflow.db.session import get_db


class TestSessionLifecycle:
    """Unit tests for database session lifecycle management and transaction safety."""

    @pytest.mark.unit
    def test_get_db_yields_session_and_closes_normally(self) -> None:
        """Verify get_db yields an active session and closes it upon exit."""
        mock_session = MagicMock()
        with patch("financeflow.db.session.SessionLocal", return_value=mock_session):
            db_gen = get_db()
            session = next(db_gen)
            assert session is mock_session
            mock_session.close.assert_not_called()

            # Finish generator execution
            with pytest.raises(StopIteration):
                next(db_gen)

            mock_session.close.assert_called_once()
            mock_session.rollback.assert_not_called()

    @pytest.mark.unit
    def test_get_db_rolls_back_and_closes_on_exception(self) -> None:
        """Verify get_db executes a rollback and closes session when an exception occurs."""
        mock_session = MagicMock()
        with patch("financeflow.db.session.SessionLocal", return_value=mock_session):
            db_gen = get_db()
            session = next(db_gen)
            assert session is mock_session

            # Simulate exception during consumer request processing
            with pytest.raises(RuntimeError, match="Transaction error"):
                db_gen.throw(RuntimeError("Transaction error"))

            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()
