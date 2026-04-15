{
  description = "Agents Loop Development Environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python312
            uv
            go-task
            ruff
            mypy
            gdal
            geos
            direnv
            stdenv.cc.cc.lib
            zlib # Required by some Python wheels
          ];

          shellHook = ''
            echo "Basemapper Dev Environment Loaded"
            
            # Allow dynamically linked C extensions (like grpcio) to find standard libraries
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib ]}:$LD_LIBRARY_PATH"
            export LD_LIBRARY_PATH="/run/current-system/sw:$LD_LIBRARY_PATH"

            # Fix VIRTUAL_ENV mismatch warning by ensuring it points to the local project environment
            # This overrides any VIRTUAL_ENV inherited from parent directories via direnv source_up
            export VIRTUAL_ENV="$(pwd)/.venv"
            export VIRTUAL_ENV_DISABLE_PROMPT=1
            export PATH="$VIRTUAL_ENV/bin:$PATH"
            
            # Ensure PYTHONPATH includes our source directory
            export PYTHONPATH="$(pwd)/src:$PYTHONPATH"
          '';
        };
      });
}
