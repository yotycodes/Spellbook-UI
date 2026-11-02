import launch

if not launch.is_installed("onnxruntime"):
    launch.run_pip("install onnxruntime", "onnxruntime for Prompt Library tagger")
