# Integration tests for simple_httpfs
# Tests include:
# - Building image and loading into docker daemon
# - Running container
# - Using httpfs to obtain files from an "upstream" service (running on the network in a separate VM)
# - Measuring throughput with a range of file sizes
# - Checking caching behaviour

{ system ? builtins.currentSystem }:

let
  pkgs = import <nixpkgs> { inherit system; };
  nixos-lib = import (<nixpkgs> + "/nixos/lib") { };

  dockerTag = "${system}-test-latest";

  stream-simple-httpfs-container-image = import ./simple-httpfs-docker.nix {
    inherit pkgs dockerTag;
  };

  testFileContent = "Hello, world! I'm a text file served from a remote machine!";

  maxFileSizeBytes = 1024 * 1024 * 10; # 10MB

  test = {
    name = "metomic-simple-httpfs";

    nodes = {
      upstream = { nodes, config, pkgs, ... }:
        {
          virtualisation.graphics = false;

          services.nginx = {
            enable = true;
            virtualHosts."upstream-service" = {
              locations."/" = {
                root = "/var/www";

                # Optimise for fast serving of static content
                extraConfig = ''
                  sendfile on;
                  tcp_nopush on;
                  tcp_nodelay on;
                '';
              };
            };
          };

          system.activationScripts.setupNginxFiles = pkgs.lib.stringAfter [ "var" ] ''
            mkdir -p /var/www
            chmod -R nginx /var/www

            # Add some dummy data to the "upstream" server for testing purposes:
            # - A 1MB, 5MB, 10MM and 20MB file with random content:
            for size in 1 5 10 20; do
              dd if=/dev/urandom "of=/var/www/testfile-''${size}m.bin" bs=1024 count=$((size * 1024))
            done

            # - A small text file of known content:
            echo -n "${testFileContent}" > /var/www/testfile.txt
          '';

          networking.firewall.enable = false;
        };

      server = { nodes, config, pkgs, ... }:
        {
          virtualisation = {
            docker.enable = true;
            cores = 2;
            graphics = false;
          };
        };
    };

    testScript = ''
      import re

      start_all()

      server.wait_for_unit("docker.service")
      upstream.wait_for_unit("nginx.service")

      with subtest("Container launches in background"):
        server.succeed("${stream-simple-httpfs-container-image} | docker load")
        server.succeed("""\
          docker run -d \\
                     --name httpfs \\
                     --network=host \\
                     --cap-add sys_admin \\
                     --device /dev/fuse \\
                     -v /tmp:/app:rshared \\
                     -e MAX_FILE_SIZE_BYTES=${toString maxFileSizeBytes} \\
                     simple-httpfs:${dockerTag} \\
        """)

      with subtest("Container attempts to mount FUSE filesystem"):
        server.wait_for_console_text("Mounting HTTP Filesystem")

      with subtest("Remote file path should exist"):
        server.wait_until_succeeds("test -e /tmp/httpfs/upstream/testfile.txt", timeout = 10)

      with subtest("Downloads remote file and obtains correct content"):
        text = server.succeed("cat /tmp/httpfs/upstream/testfile.txt")
        print(f"Received text from upstream service: {text}")
        assert text == "${testFileContent}", "File content received did not match expected text";

      with subtest("Limits max path length (security measure)"):
        # Should return ENOENT (file doesn't exist)
        server.fail("test -e /tmp/httpfs/upstream/foooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooo/baaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaar.txt")

      with subtest("Aborts reading file if remote file exceeds file size limit"):
        server.fail("cat /tmp/httpfs/upstream/testfile-20m.bin")

      with subtest("Measure performance with 1MB file"):
        text = server.succeed("dd if=/tmp/httpfs/upstream/testfile-1m.bin of=/dev/null bs=1024 2>&1 | grep copied")
        match = re.search(r', (\d+(\.\d+)?) MB/s', text)
        if match:
          print(f"Throughput downloading 1MB file: {match.group(1)} MB/s")

      with subtest("Measure performance with 5MB file"):
        text = server.succeed("dd if=/tmp/httpfs/upstream/testfile-5m.bin of=/dev/null bs=1024 2>&1 | grep copied")
        match = re.search(r', (\d+(\.\d+)?) MB/s', text)
        if match:
          print(f"Throughput downloading 5MB file: {match.group(1)} MB/s")

      initial_throughput = 0.0
      with subtest("Measure performance with 10MB file"):
        text = server.succeed("dd if=/tmp/httpfs/upstream/testfile-10m.bin of=/dev/null bs=1024 2>&1 | grep copied")
        match = re.search(r', (\d+(\.\d+)?) MB/s', text)
        if match:
          initial_throughput = float(match.group(1))
        print(f"Throughput downloading 10MB file: {initial_throughput} MB/s")

      final_throughput = 0.0
      with subtest("File data is stored in a cache, so doesn't hit the upstream again on immediate re-access"):
        text = server.succeed("dd if=/tmp/httpfs/upstream/testfile-10m.bin of=/dev/null bs=1024 2>&1 | grep copied")
        match = re.search(r', (\d+(\.\d+)?) MB/s', text)
        if match:
          final_throughput = float(match.group(1))
        print(f"Throughput on repeat access to 10MB file: {final_throughput} MB/s")
        assert final_throughput > initial_throughput, "Second download does not appear to be served from the cache - expected {final_throughput} to be greater than {initial_throughput}"
    '';
  };

in nixos-lib.runTest {
  imports = [ test ];
  hostPkgs = pkgs;
}
