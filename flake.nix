{
  description = "AgentsLoop CLI development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python312
            uv
            ruff
            mypy
            direnv
            gemini-cli
            github-copilot-cli
            nodejs
          ];

          shellHook = ''
            echo "AgentsLoop CLI dev environment loaded"

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
