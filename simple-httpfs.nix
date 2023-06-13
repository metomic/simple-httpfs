{ pkgs ? import <nixpkgs> {} }:

pkgs.python3Packages.buildPythonPackage rec {
  name = "simple-httpfs";
  version = "git-master";

  src = ./.;
  doCheck = false;

  propagatedBuildInputs = with pkgs.python3Packages; [ numpy boto3 diskcache fusepy requests slugid tenacity ];
}
