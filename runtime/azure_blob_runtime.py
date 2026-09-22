"""Azure Blob transport for the existing file and reviewed snapshot workflow."""
import files_runtime
from azure_blob_reader import scan
files_runtime.scan = scan
runtime_identity = files_runtime.runtime_identity
if __name__ == '__main__': files_runtime.workflow.main()
