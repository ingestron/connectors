"""SQL Server transport through the existing reviewed local snapshot boundary."""
import files_runtime
from sql_server_reader import scan

files_runtime.scan = scan
runtime_identity = files_runtime.runtime_identity

if __name__ == '__main__':
    files_runtime.workflow.main()
