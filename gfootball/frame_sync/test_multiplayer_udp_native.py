"""Real GameEnv UDP match acceptance, explicitly required without skips."""
from gfootball.frame_sync import test_multiplayer_native as native_tests


class NativeMultiplayerUDPTest(native_tests.NativeMultiplayerTest):
  transport = 'udp'
