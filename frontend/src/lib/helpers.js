export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function downloadTextFile(content, filename) {
  const blob = new Blob([content], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function formatCredentialBlock(username, password, dns, m3uUrl) {
  let block = `Username: ${username}\nPassword: ${password}\nDNS: ${dns}`;
  if (m3uUrl) {
    block += `\nM3U URL: ${m3uUrl}`;
  }
  return block;
}
