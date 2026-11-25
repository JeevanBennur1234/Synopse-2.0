export const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;

const ALLOWED_MIME_TYPES = new Set([
  "application/pdf",
  "image/png",
  "image/jpeg",
]);

const ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg"];

export function validateSelectedFile(file) {
  if (!file) {
    return { valid: false, error: "Please choose a PDF, PNG, or JPEG document." };
  }
  const lowerName = (file.name || "").toLowerCase();
  const hasAllowedExt = ALLOWED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
  const hasAllowedMime = file.type ? ALLOWED_MIME_TYPES.has(file.type) : false;

  if (!hasAllowedExt && !hasAllowedMime) {
    return {
      valid: false,
      error: `Unsupported file type (${file.name}). Only PDF, PNG, and JPEG files are accepted.`,
    };
  }
  if (file.type && !ALLOWED_MIME_TYPES.has(file.type) && !hasAllowedExt) {
    return {
      valid: false,
      error: `Unsupported MIME type (${file.type}). Upload a PDF, PNG, or JPEG file.`,
    };
  }
  if (file.size === 0) {
    return { valid: false, error: "The selected file is empty (0 bytes)." };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      valid: false,
      error: `File exceeds the 15 MB limit (${formatBytes(file.size)}).`,
    };
  }
  return { valid: true, error: null };
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export const RISK_STYLES = {
  low: {
    label: "Low Risk",
    badge: "bg-emerald-50 text-emerald-800 border-emerald-200",
    bar: "bg-emerald-600",
    ring: "text-emerald-700",
    panel: "border-emerald-200 bg-emerald-50/50",
    summary:
      "All completed forensic and consistency checks passed within normal thresholds. Continue standard verification before financial settlement.",
  },
  medium: {
    label: "Medium Risk",
    badge: "bg-amber-50 text-amber-800 border-amber-200",
    bar: "bg-amber-500",
    ring: "text-amber-700",
    panel: "border-amber-200 bg-amber-50/50",
    summary:
      "One or more localized anomalies or discrepancies were flagged. Manual document review is recommended before approval.",
  },
  high: {
    label: "High Risk",
    badge: "bg-red-50 text-red-800 border-red-200",
    bar: "bg-red-600",
    ring: "text-red-700",
    panel: "border-red-200 bg-red-50/50",
    summary:
      "Significant forensic or arithmetic inconsistencies were detected. Escalate for independent verification using original source records.",
  },
  inconclusive: {
    label: "Inconclusive",
    badge: "bg-slate-100 text-slate-700 border-slate-300",
    bar: "bg-slate-400",
    ring: "text-slate-600",
    panel: "border-slate-200 bg-slate-50",
    summary:
      "Insufficient conclusive evidence to compute a reliable overall risk score. Missing or unavailable checks do not imply the document is clean.",
  },
};

export const FINDING_STATUS_STYLES = {
  passed: {
    label: "Passed",
    badge: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  suspicious: {
    label: "Suspicious",
    badge: "bg-red-50 text-red-700 border-red-200",
  },
  inconclusive: {
    label: "Inconclusive",
    badge: "bg-slate-100 text-slate-700 border-slate-200",
  },
  not_applicable: {
    label: "Not Applicable",
    badge: "bg-slate-50 text-slate-500 border-slate-200",
  },
  error: {
    label: "Error",
    badge: "bg-amber-50 text-amber-700 border-amber-200",
  },
};

const VISUAL_DETECTORS = new Set([
  "ela",
  "copy_move",
  "noise_inconsistency",
  "image_metadata",
  "visual",
]);

const FILE_DETECTORS = new Set([
  "file_forensics",
  "pdf_metadata",
  "pdf_structure",
  "qr_code",
  "qr",
  "font_check",
]);

const CONSISTENCY_DETECTORS = new Set([
  "consistency",
  "gstin",
  "tax_math",
  "total_mismatch",
  "bank_balance",
  "running_balance",
  "arithmetic",
]);

export function categorizeFinding(name = "") {
  const key = name.toLowerCase();
  if (VISUAL_DETECTORS.has(key) || key.includes("visual") || key.includes("ela") || key.includes("noise") || key.includes("copy_move")) {
    return "visual";
  }
  if (FILE_DETECTORS.has(key) || key.includes("pdf") || key.includes("file") || key.includes("qr") || key.includes("metadata")) {
    return "file_forensics";
  }
  if (CONSISTENCY_DETECTORS.has(key) || key.includes("gstin") || key.includes("tax") || key.includes("balance") || key.includes("total") || key.includes("consistency")) {
    return "consistency";
  }
  return "other";
}

export function groupFindings(findings = []) {
  const groups = {
    visual: [],
    file_forensics: [],
    consistency: [],
    other: [],
  };
  findings.forEach((finding, index) => {
    const category = categorizeFinding(finding.name);
    groups[category].push({ ...finding, _index: index, _category: category });
  });
  return groups;
}

export function formatDetectorLabel(name = "") {
  const labels = {
    ela: "Error Level Analysis (ELA)",
    copy_move: "Copy-Move Clone Detection",
    noise_inconsistency: "Local Noise Consistency",
    image_metadata: "Image EXIF / Metadata Audit",
    file_forensics: "File & PDF Structure Forensics",
    consistency: "Business & Arithmetic Consistency",
    gstin: "GSTIN Format & Checksum",
    tax_math: "Tax & Total Arithmetic",
    running_balance: "Bank Statement Running Balance",
  };
  if (labels[name]) return labels[name];
  return name
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/**
 * Scale a bounding box defined in original rendered page pixels (`pageWidth x pageHeight`)
 * to the currently displayed image dimensions (`displayWidth x displayHeight`).
 */
export function scaleBoundingBox(box, pageWidth, pageHeight, displayWidth, displayHeight) {
  if (
    !box ||
    !pageWidth ||
    !pageHeight ||
    !displayWidth ||
    !displayHeight
  ) {
    return null;
  }
  const scaleX = displayWidth / pageWidth;
  const scaleY = displayHeight / pageHeight;
  return {
    left: Math.round(box.x * scaleX * 100) / 100,
    top: Math.round(box.y * scaleY * 100) / 100,
    width: Math.max(2, Math.round(box.w * scaleX * 100) / 100),
    height: Math.max(2, Math.round(box.h * scaleY * 100) / 100),
  };
}

export function formatFieldLabel(key = "") {
  const map = {
    gstin: "GSTIN",
    ifsc: "IFSC Code",
    invoice_number: "Invoice Number",
    dates: "Document Dates",
    subtotal: "Subtotal",
    cgst: "CGST",
    sgst: "SGST",
    igst: "IGST",
    discount: "Discount",
    total: "Grand Total",
    opening_balance: "Opening Balance",
    closing_balance: "Closing Balance",
  };
  return map[key] || formatDetectorLabel(key);
}
