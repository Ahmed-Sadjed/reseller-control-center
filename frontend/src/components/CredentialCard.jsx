import { useNavigate } from 'react-router-dom';
import CopyButton from './CopyButton';
import { formatCredentialBlock, downloadTextFile } from '../lib/helpers';

export default function CredentialCard({ credential, index }) {
  const navigate = useNavigate();
  const { username, password, dns_domain: dns, m3u_url: m3uUrl, expires_at: expiresAt, provider_adapter_key: providerKey } = credential;
  const block = formatCredentialBlock(username, password, dns, m3uUrl);
  const truncatedDns = dns.length > 50 ? dns.substring(0, 47) + '...' : dns;
  const truncatedM3uUrl = m3uUrl && m3uUrl.length > 50 ? m3uUrl.substring(0, 47) + '...' : m3uUrl;

  const handleCopyAll = async () => {
    await navigator.clipboard.writeText(block);
  };

  const handleDownload = () => {
    downloadTextFile(block, `credential-${username}.txt`);
  };

  return (
    <div className="bg-white rounded-lg shadow border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-gray-500">#{index + 1}</span>
        <span className="text-xs text-gray-400">
          Expires: {expiresAt ? new Date(expiresAt).toLocaleDateString() : 'Lifetime'}
        </span>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs text-gray-500">USERNAME</span>
            <p className="text-sm font-mono text-gray-900">{username}</p>
          </div>
          <CopyButton text={username} label="Copy" />
        </div>
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs text-gray-500">PASSWORD</span>
            <p className="text-sm font-mono text-gray-900">{password}</p>
          </div>
          <CopyButton text={password} label="Copy" />
        </div>
        <div className="flex items-center justify-between">
          <div className="flex-1 min-w-0 mr-2">
            <span className="text-xs text-gray-500">DNS</span>
            <p className="text-sm font-mono text-gray-900 truncate">{truncatedDns}</p>
          </div>
          <CopyButton text={dns} label="Copy" />
        </div>
        {m3uUrl && (
          <div className="flex items-center justify-between">
            <div className="flex-1 min-w-0 mr-2">
              <span className="text-xs text-gray-500">M3U URL</span>
              <p className="text-sm font-mono text-gray-900 truncate">{truncatedM3uUrl}</p>
            </div>
            <CopyButton text={m3uUrl} label="Copy" />
          </div>
        )}
      </div>
      <div className="mt-4 flex space-x-3">
        <button
          onClick={handleCopyAll}
          className="flex-1 px-3 py-2 text-sm font-medium text-white bg-green-600 rounded hover:bg-green-700 transition-colors"
        >
          Copy All
        </button>
        <button
          onClick={handleDownload}
          className="flex-1 px-3 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 transition-colors"
        >
          Download .txt
        </button>
        {providerKey === 'hotplayer' && (
          <button
            onClick={() => navigate(`/credentials/${credential.id}/manage`)}
            className="px-3 py-2 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 transition-colors"
          >
            Manage Device
          </button>
        )}
      </div>
    </div>
  );
}
