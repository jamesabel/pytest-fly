"""Application-wide constants."""

# Environment variable that overrides the default test-results DB directory.
PYTEST_FLY_DATA_DIR_STRING = "PYTEST_FLY_DATA_DIR"

# Environment variable carrying the workspace directory (the directory pytest-fly was launched
# from) into spawned child processes, which re-import modules fresh and so lose the in-process
# binding established by paths.init_workspace().
PYTEST_FLY_WORKSPACE_STRING = "PYTEST_FLY_WORKSPACE"

# Environment variable carrying the resolved faulthandler setting into spawned child processes,
# which re-import modules fresh and so cannot see the parent's preference lookup.
PYTEST_FLY_FAULTHANDLER_STRING = "PYTEST_FLY_FAULTHANDLER"
