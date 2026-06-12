export type ChatConnectorType = "imap";

export interface ChatConnectorPreset {
  id: string;
  label: { zh: string; en: string };
  type: ChatConnectorType;
  imap_host: string;
  imap_port: number;
  imap_use_ssl: boolean;
  emailHint?: { zh: string; en: string };
  passwordHint?: { zh: string; en: string };
}

export const CHAT_CONNECTORS: ChatConnectorPreset[] = [
  {
    id: "byd-mail",
    label: { zh: "企业邮箱", en: "Corporate Mail" },
    type: "imap",
    imap_host: "imap.byd.com",
    imap_port: 1993,
    imap_use_ssl: true,
    emailHint: { zh: "name@byd.com", en: "name@byd.com" },
    passwordHint: { zh: "邮箱密码", en: "Mailbox password" },
  },
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
  if (!preset) return false;
  return preset.imap_host === mailbox.imap_host && preset.imap_port === mailbox.imap_port;
}
