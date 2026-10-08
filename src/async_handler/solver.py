"""Asynchronous solver handler for COMSOL simulations."""

import threading
from typing import Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import traceback


class SolverStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SolverProgress:
    """Progress information for a solving operation."""
    status: SolverStatus = SolverStatus.IDLE
    progress: float = 0.0
    message: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    study_name: Optional[str] = None
    model_name: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "error": self.error,
            "traceback": self.traceback,
            "progress_source": "lifecycle_only_not_comsol_solver",
            "study_name": self.study_name,
            "model_name": self.model_name,
            "elapsed_seconds": (
                (self.end_time or datetime.now()) - self.start_time
            ).total_seconds() if self.start_time else 0,
        }


class AsyncSolver:
    """Manages asynchronous solving operations for COMSOL models."""
    
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._progress: SolverProgress = SolverProgress()
        self._cancel_flag: bool = False
        self._lock: threading.Lock = threading.Lock()
    
    @property
    def progress(self) -> SolverProgress:
        with self._lock:
            return self._progress
    
    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._progress.status == SolverStatus.RUNNING
    
    def start_solve(
        self,
        model,
        study_name: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> bool:
        """
        Start solving a study in a background thread.
        
        Args:
            model: The COMSOL model to solve
            study_name: Name of the study to solve (None for all studies)
            progress_callback: Optional callback for progress updates
        
        Returns:
            True if solving started, False if already running
        """
        with self._lock:
            if self._progress.status == SolverStatus.RUNNING:
                return False
            
            self._cancel_flag = False
            self._progress = SolverProgress(
                status=SolverStatus.RUNNING,
                progress=0.0,
                message="Starting solver...",
                start_time=datetime.now(),
                study_name=study_name,
                model_name=model.name() if hasattr(model, 'name') else None,
            )
        
        from ..tools.errors import CALL_ID,error_record
        originating_call_id=CALL_ID.get()

        def solve_thread():
            try:
                with self._lock:
                    self._progress.message = f"Solving study: {study_name or 'all'} (COMSOL percentage unavailable)"
                if self._cancel_flag:
                    self._set_cancelled()
                    return

                model.solve(study_name)
                
                if self._cancel_flag:
                    self._set_cancelled()
                    return
                
                with self._lock:
                    self._progress.status = SolverStatus.COMPLETED
                    self._progress.progress = 1.0
                    self._progress.message = "Solving completed successfully."
                    self._progress.end_time = datetime.now()
                
                if progress_callback:
                    progress_callback(1.0, "Completed")
                    
            except Exception as e:
                error_record(e,"study_solve_async",call_id=originating_call_id,source="solver_thread")
                error_msg = str(e)
                tb = traceback.format_exc()
                
                with self._lock:
                    self._progress.status = SolverStatus.FAILED
                    self._progress.error = error_msg
                    self._progress.traceback = tb
                    self._progress.message = f"Solving failed: {error_msg}"
                    self._progress.end_time = datetime.now()
                
                if progress_callback:
                    progress_callback(-1.0, f"Error: {error_msg}")
        
        self._thread = threading.Thread(target=solve_thread, daemon=True)
        self._thread.start()
        return True
    
    def _set_cancelled(self):
        """Set status to cancelled."""
        with self._lock:
            self._progress.status = SolverStatus.CANCELLED
            self._progress.message = "Solving was cancelled by user."
            self._progress.end_time = datetime.now()
    
    def cancel(self) -> bool:
        """No verified public shared-JVM interrupt API. Never simulate cancellation."""
        return False

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for the solving operation to complete.
        
        Args:
            timeout: Maximum time to wait in seconds (None for indefinite)
        
        Returns:
            True if solving completed, False if timeout reached
        """
        if self._thread is None:
            return True
        
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()
    
    def get_progress(self) -> dict:
        """Get current solving progress as a dictionary."""
        return self.progress.to_dict()
    
    def reset(self):
        """Reset the solver state."""
        with self._lock:
            self._progress = SolverProgress()
            self._cancel_flag = False


async_solver = AsyncSolver()
