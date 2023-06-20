{ pkgs ? import <nixpkgs> {} }:

pkgs.python3Packages.buildPythonPackage rec {
  name = "simple-httpfs";
  version = "git-master";

  src = ./python;
  doCheck = false;

  propagatedBuildInputs = with pkgs.python3Packages; [
    fusepy
    requests
    tenacity
  ];
}
