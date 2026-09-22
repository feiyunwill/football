"""Force the UI-feed/logic-ready interleaving using events and real owner cleanup."""
import threading
from unittest import mock
from gfootball.frame_sync import graphical_runtime as runtime
from gfootball.frame_sync import test_graphical_runtime as harness

def test_quit_between_input_feed_and_ready_finalizes_replay():
  case=harness.GraphicalRuntimeTest("test_window_quit_before_first_input_finalizes_zero_frame_replay")
  case.setUp()
  entered=threading.Event();observed=[]
  original_feed=runtime.InputBuffer.feed
  original_run=runtime.LocalPlayer.run
  def run(owner,*args,**kwargs):
    entered.set()
    return original_run(owner,*args,**kwargs)
  def feed(inputs,**kwargs):
    result=original_feed(inputs,**kwargs)
    if kwargs.get("quit") and not entered.is_set():
      # Hold the UI before ready.set; the worker must handle the user request.
      # No fixed sleep determines the desired ordering.
      observed.append(entered.wait(2))
    return result
  try:
    with mock.patch.object(runtime.InputBuffer,"feed",feed),mock.patch.object(runtime.LocalPlayer,"run",run):
      case.test_window_quit_before_first_input_finalizes_zero_frame_replay()
    assert observed==[True],"The forced startup handoff was not observed"
    assert entered.is_set()
  finally:
    try:case.tearDown()
    finally:case.doCleanups()
