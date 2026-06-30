const EXCEL_SUFFIXES = [".xlsx", ".xls", ".xlsm", ".csv"];

export function isExcelFilename(name: string): boolean {
  const lower = name.toLowerCase();
  return EXCEL_SUFFIXES.some((ext) => lower.endsWith(ext));
}

function fileFromRelativePath(file: File, relativePath: string): File {
  const base = relativePath.split("/").pop() || file.name;
  if (base === file.name) return file;
  return new File([file], base, { type: file.type, lastModified: file.lastModified });
}

function filterWebkitFiles(fileList: FileList, recursive: boolean): File[] {
  const files = Array.from(fileList);
  return files
    .filter((f) => {
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      if (!isExcelFilename(rel)) return false;
      if (recursive) return true;
      const depth = rel.split("/").length - 1;
      return depth <= 1;
    })
    .map((f) => {
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      return fileFromRelativePath(f, rel);
    });
}

async function collectFromDirectoryHandle(
  handle: FileSystemDirectoryHandle,
  recursive: boolean,
): Promise<File[]> {
  const out: File[] = [];
  const entries = (
    handle as unknown as { entries(): AsyncIterableIterator<[string, FileSystemHandle]> }
  ).entries();
  for await (const [, entry] of entries) {
    if (entry.kind === "file") {
      const file = await (entry as FileSystemFileHandle).getFile();
      if (isExcelFilename(file.name)) out.push(file);
    } else if (recursive && entry.kind === "directory") {
      out.push(...(await collectFromDirectoryHandle(entry as FileSystemDirectoryHandle, true)));
    }
  }
  return out;
}

function pickViaHiddenInput(recursive: boolean): Promise<File[]> {
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.setAttribute("webkitdirectory", "");
    input.accept = ".xlsx,.xls,.xlsm,.csv";
    input.style.display = "none";
    input.onchange = () => {
      if (!input.files?.length) {
        resolve([]);
        return;
      }
      resolve(filterWebkitFiles(input.files, recursive));
      input.remove();
    };
    input.oncancel = () => {
      resolve([]);
      input.remove();
    };
    document.body.appendChild(input);
    input.click();
  });
}

/** Pick Excel files from a local folder (browser directory picker). */
export async function pickLocalExcelFiles(recursive: boolean): Promise<{ files: File[]; folderLabel: string }> {
  if (typeof window !== "undefined" && "showDirectoryPicker" in window) {
    try {
      const handle = await (window as Window & { showDirectoryPicker: () => Promise<FileSystemDirectoryHandle> }).showDirectoryPicker();
      const files = await collectFromDirectoryHandle(handle, recursive);
      return { files, folderLabel: handle.name };
    } catch (err) {
      if ((err as DOMException)?.name === "AbortError") return { files: [], folderLabel: "" };
      throw err;
    }
  }
  const files = await pickViaHiddenInput(recursive);
  const first = files[0] as (File & { webkitRelativePath?: string }) | undefined;
  const folderLabel = first?.webkitRelativePath?.split("/")[0] || "";
  return { files, folderLabel };
}

export async function uploadExcelFilesInBatches(
  upload: (batch: File[]) => Promise<unknown>,
  files: File[],
  batchSize = 20,
): Promise<void> {
  for (let i = 0; i < files.length; i += batchSize) {
    await upload(files.slice(i, i + batchSize));
  }
}
