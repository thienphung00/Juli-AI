"use client";

import {
  useId,
  useState,
  type ChangeEvent,
  type ComponentPropsWithoutRef,
} from "react";

import { FormError, FormField, FormLabel } from "./form";

const ACCEPTED_IMAGE_MIMETYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
]);

const MAGIC_BYTES_SIGNATURES = {
  "image/jpeg": [0xff, 0xd8, 0xff],
  "image/png": [0x89, 0x50, 0x4e, 0x47],
  "image/webp": [0x52, 0x49, 0x46, 0x46],
  "image/gif": [0x47, 0x49, 0x46],
} as const;

export interface FileUploadFieldProps
  extends Omit<
    ComponentPropsWithoutRef<"input">,
    "id" | "type" | "accept" | "aria-describedby" | "onChange"
  > {
  errorMessage?: string;
  helperText?: string;
  id?: string;
  label: string;
  maxSize?: number;
  onChange?: (file: File | null) => void;
  required?: boolean;
}

async function verifyImageSignature(file: File): Promise<boolean> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const buffer = reader.result as ArrayBuffer;
      const bytes = new Uint8Array(buffer).slice(0, 4);

      if (file.type === "image/jpeg") {
        resolve(bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff);
      } else if (file.type === "image/png") {
        resolve(
          bytes[0] === 0x89 &&
            bytes[1] === 0x50 &&
            bytes[2] === 0x4e &&
            bytes[3] === 0x47,
        );
      } else if (file.type === "image/gif") {
        resolve(
          bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46,
        );
      } else if (file.type === "image/webp") {
        const isRiff = bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46;
        if (!isRiff) {
          resolve(false);
          return;
        }
        // WebP check: bytes 8-11 should be "WEBP"
        const slice = new Uint8Array(buffer).slice(8, 12);
        const isWebp =
          slice[0] === 0x57 && slice[1] === 0x45 && slice[2] === 0x42 && slice[3] === 0x50;
        resolve(isWebp);
      } else {
        resolve(false);
      }
    };
    reader.readAsArrayBuffer(file.slice(0, 12));
  });
}

async function verifyImageDecodable(file: File): Promise<boolean> {
  try {
    const createBitmap =
      typeof globalThis.createImageBitmap === "function"
        ? globalThis.createImageBitmap
        : null;

    if (createBitmap) {
      const bitmap = await createBitmap(file);
      bitmap.close();
      return true;
    }
    return true;
  } catch {
    return false;
  }
}

function getFileExtension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

export function FileUploadField({
  errorMessage: errorMessageProp,
  helperText = "Chỉ hỗ trợ các tệp ảnh (JPEG, PNG, WebP, GIF).",
  id: idProp,
  label,
  maxSize = 10 * 1024 * 1024,
  onChange,
  required,
  ...inputProps
}: FileUploadFieldProps) {
  const generatedId = useId();
  const inputId = idProp ?? generatedId;
  const errorId = `${inputId}-error`;
  const helperId = `${inputId}-helper`;
  const [errorMessage, setErrorMessage] = useState<string | undefined>(
    errorMessageProp,
  );
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;

    if (!file) {
      setErrorMessage(undefined);
      setSelectedFile(null);
      onChange?.(null);
      return;
    }

    // Check if file is an image type
    if (!ACCEPTED_IMAGE_MIMETYPES.has(file.type)) {
      setErrorMessage(
        "Tệp này không phải ảnh được hỗ trợ. Vui lòng chọn ảnh JPG, PNG, WebP hoặc GIF.",
      );
      setSelectedFile(null);
      onChange?.(null);
      return;
    }

    // Check file size
    if (file.size > maxSize) {
      const maxSizeMB = Math.ceil(maxSize / (1024 * 1024));
      setErrorMessage(
        `Ảnh quá lớn (dung lượng tối đa ${maxSizeMB}MB). Vui lòng chọn ảnh nhỏ hơn.`,
      );
      setSelectedFile(null);
      onChange?.(null);
      return;
    }

    // Verify file signature/magic bytes
    const isValidSignature = await verifyImageSignature(file);
    if (!isValidSignature) {
      setErrorMessage(
        "Tệp không nhận dạng được hoặc không phải ảnh hợp lệ. Vui lòng kiểm tra tệp và thử lại.",
      );
      setSelectedFile(null);
      onChange?.(null);
      return;
    }

    // Verify file is a decodable image (not corrupt or truncated)
    const isDecodable = await verifyImageDecodable(file);
    if (!isDecodable) {
      setErrorMessage(
        "Tệp ảnh bị hỏng hoặc không đầy đủ. Vui lòng chọn ảnh khác hoặc tải lại ảnh này.",
      );
      setSelectedFile(null);
      onChange?.(null);
      return;
    }

    // All checks passed
    setErrorMessage(undefined);
    setSelectedFile(file);
    onChange?.(file);
  };

  const describedBy = [
    errorMessage ? errorId : null,
    helperText && !errorMessage ? helperId : null,
  ]
    .filter(Boolean)
    .join(" ");
  const hasError = Boolean(errorMessage);

  return (
    <FormField data-testid={`field-${inputId}`}>
      <div className="juli-form__label-container">
        <FormLabel htmlFor={inputId} required={required}>
          {label}
        </FormLabel>
      </div>
      <div className="juli-form__file-wrapper">
        <input
          accept="image/jpeg,image/png,image/webp,image/gif"
          aria-describedby={describedBy || undefined}
          aria-invalid={hasError || undefined}
          className="juli-form__file-input"
          id={inputId}
          onChange={handleFileChange}
          required={required}
          type="file"
          {...inputProps}
        />
        {selectedFile ? (
          <p className="juli-form__file-selected">{selectedFile.name}</p>
        ) : null}
      </div>
      {errorMessage ? <FormError id={errorId}>{errorMessage}</FormError> : null}
      {helperText && !errorMessage ? (
        <p className="juli-form__helper" id={helperId}>
          {helperText}
        </p>
      ) : null}
    </FormField>
  );
}
