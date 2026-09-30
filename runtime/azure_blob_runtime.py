"""Azure Blob transport for the reviewed single-object snapshot workflow."""
import connector_kit as kit
from azure_blob_reader import scan

workflow = kit.install_single(scan)
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
