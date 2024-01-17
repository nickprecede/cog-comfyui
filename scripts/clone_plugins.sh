#!/bin/bash

# This script is used to clone specific versions of repositories.
# It takes a list of repositories and their commit hashes, clones them into a specific directory,
# and then checks out to the specified commit.

# List of repositories and their commit hashes to clone
# Each entry in the array is a string containing the repository URL and the commit hash separated by a space.
repos=(
  "https://github.com/cubiq/ComfyUI_IPAdapter_plus 4e898fe"
  "https://github.com/Fannovel16/comfyui_controlnet_aux 6d6f63c"
  "https://github.com/ltdrdata/ComfyUI-Inspire-Pack c8231dd"
  "https://github.com/theUpsider/ComfyUI-Logic fb88973"
  "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved d2bf367"
)

# Destination directory
# This is where the repositories will be cloned into.
dest_dir="ComfyUI/custom_nodes/"

# Loop over each repository in the list
for repo in "${repos[@]}"; do
  # Extract the repository URL and the commit hash from the string
  repo_url=$(echo $repo | cut -d' ' -f1)
  commit_hash=$(echo $repo | cut -d' ' -f2)

  # Extract the repository name from the URL by removing the .git extension
  repo_name=$(basename "$repo_url" .git)

  # Clone the repository into the destination directory
  echo "Cloning $repo_url into $dest_dir$repo_name and checking out to commit $commit_hash"
  git clone "$repo_url" "$dest_dir$repo_name"

  # Use a subshell to avoid changing the main shell's working directory
  # Inside the subshell, change to the repository's directory and checkout to the specific commit
  (cd "$dest_dir$repo_name" && git checkout "$commit_hash")
done