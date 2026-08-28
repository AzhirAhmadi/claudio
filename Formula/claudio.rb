class Claudio < Formula
  include Language::Python::Virtualenv

  desc "Spoken notifications for Claude Code - hear which session needs you and why"
  homepage "https://github.com/AzhirAhmadi/claudio"
  url "https://github.com/AzhirAhmadi/claudio/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_TARBALL_SHA256"
  license "MIT"
  head "https://github.com/AzhirAhmadi/claudio.git", branch: "main"

  depends_on "python@3.13"
  depends_on :macos

  # Regenerate with:  brew update-python-resources Formula/claudio.rb
  resource "edge-tts" do
    url "https://files.pythonhosted.org/packages/source/e/edge-tts/edge_tts-6.1.19.tar.gz"
    sha256 "REPLACE_WITH_EDGE_TTS_SHA256"
  end

  resource "tomli-w" do
    url "https://files.pythonhosted.org/packages/source/t/tomli_w/tomli_w-1.2.0.tar.gz"
    sha256 "REPLACE_WITH_TOMLI_W_SHA256"
  end

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Finish setting up with:
        claudio setup

      That writes ~/.config/claudio/config.toml and wires the Claude Code hooks.
      Restart Claude Code afterwards so it loads them.

      Check everything with:
        claudio doctor
    EOS
  end

  test do
    assert_match "claudio", shell_output("#{bin}/claudio --version")
    output = shell_output("#{bin}/claudio explain Edit --input " \
                          "'{\"file_path\":\"app/models/order.rb\"}'")
    assert_match "order", output
  end
end
