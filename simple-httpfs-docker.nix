{ system ? "aarch64-linux",
  pkgs ? import <nixpkgs> { inherit system; },
  dockerTag ? "${system}-latest",
  maxLayers ? 64
}:

let

  simple-httpfs = import ./simple-httpfs.nix { inherit pkgs; };

  startupScript = pkgs.writeShellApplication {
    name = "docker-startup";
    text = ''
       ${pkgs.busybox}/bin/umount /app/httpfs || true
       ${pkgs.busybox}/bin/mkdir -p /app/httpfs
       exec ${simple-httpfs}/bin/simple-httpfs -f --schema http --allow-other /app/httpfs
  '';
  };

in

pkgs.dockerTools.streamLayeredImage {
  name = "simple-httpfs";
  tag = dockerTag;

  inherit maxLayers;

  config = {
    Cmd = [ "${startupScript}/bin/docker-startup" ];
  };
}
