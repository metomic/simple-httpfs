# Metomic's fork of simple_httpfs

A FUSE filesystem providing access to remote content as if it were a local file.

See `test.nix` for an example of how this works in practice.

## Changes from upstream:

- Handling of non-200 statuses -> send FUSE "file not found" error back to application
- Ability to enforce max file size (env var `MAX_FILE_SIZE`)
- Optimisation for specific use case of fully linear reads - the full file is downloaded into memory on first block request 
- Remove need for trailing dots in file path (was previously used to signal end of file path)
- Enforce max path length

## Integration tests

Build `test.nix` to run the integration tests locally. 

These will work in emulated mode (e.g. inside Docker for Mac), but they'll run at full speed on a host with KVM available (such as larger github runners with >= 4 cores or any other linux host with nested virtualisation enabled / bare metal).
