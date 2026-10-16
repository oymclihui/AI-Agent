export type ChatConnectorType = "imap" | "wecom";

export interface ChatConnectorPreset {
  id: string;
  label: { zh: string; en: string };
  type: ChatConnectorType;
  imap_host?: string;
  imap_port?: number;
  imap_use_ssl?: boolean;
  emailHint?: { zh: string; en: string };
  passwordHint?: { zh: string; en: string };
}

export const CHAT_CONNECTORS: ChatConnectorPreset[] = [
  {
    id: "wecom-mail",
    label: { zh: "企微邮箱", en: "WeCom Mail" },
    type: "imap",
    imap_host: "imap.exmail.qq.com",
    imap_port: 993,
    imap_use_ssl: true,
    emailHint: { zh: "name@company.com", en: "name@company.com" },
    passwordHint: {
      zh: "企业邮箱密码或客户端专用密码",
      en: "Enterprise mail or client password",
    },
  },
  {
    id: "wecom-bot",
    label: { zh: "企业微信", en: "WeCom" },
    type: "wecom",
  },
];

export function connectorLabel(id: string, lang: "zh" | "en"): string {
  const preset = CHAT_CONNECTORS.find((c) => c.id === id);
  return preset ? preset.label[lang] : id;
}

export function connectorMatchesMailbox(
  connectorId: string,
  mailbox: { imap_host: string; imap_port: number } | null,
): boolean {
  if (!mailbox) return false;
  const preset = CHAT_CONNECTORS.find((c) => c.id === connectorId);
  if (!preset || preset.type !== "imap" || !preset.imap_host || preset.imap_port == null) return false;
  return preset.imap_host === mailbox.imap_host && preset.imap_port === mailbox.imap_port;
}
