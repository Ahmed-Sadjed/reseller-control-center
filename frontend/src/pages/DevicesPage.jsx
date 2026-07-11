import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import api from '../lib/axios';

const MAC_REGEX = /^([0-9A-Za-f]{2}:){5}[0-9A-Za-f]{2}$/;

const PROVIDER_BADGES = {
  hotplayer: 'bg-purple-100 text-purple-800',
  neo4k: 'bg-blue-100 text-blue-800',
  golden_api: 'bg-amber-100 text-amber-800',
  goldpanel: 'bg-green-100 text-green-800',
  mock: 'bg-gray-100 text-gray-800',
};

export default function DevicesPage() {
  const [credentials, setCredentials] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('hotplayer');

  const [checkMac, setCheckMac] = useState('');
  const [checkResult, setCheckResult] = useState(null);
  const [checking, setChecking] = useState(false);

  const [playlistFields, setPlaylistFields] = useState([{ id: 1, name: '', url: '' }]);
  const [savingPlaylists, setSavingPlaylists] = useState(false);
  const [playlistMessage, setPlaylistMessage] = useState(null);

  let nextPlaylistId = 2;
  const addPlaylistField = () => {
    setPlaylistFields(prev => [...prev, { id: nextPlaylistId++, name: '', url: '' }]);
  };
  const removePlaylistField = (index) => {
    setPlaylistFields(prev => prev.filter((_, i) => i !== index));
  };
  const handlePlaylistChange = (index, field, value) => {
    setPlaylistFields(prev => prev.map((pf, i) => i === index ? { ...pf, [field]: value } : pf));
  };

  const handleSavePlaylists = async () => {
    const valid = playlistFields
      .filter(pf => pf.url.trim())
      .map(pf => ({ url: pf.url.trim(), ...(pf.name.trim() ? { name: pf.name.trim() } : {}) }));

    if (valid.length === 0) {
      setPlaylistMessage({ type: 'error', text: 'Enter at least one playlist URL.' });
      return;
    }

    setSavingPlaylists(true);
    setPlaylistMessage(null);
    try {
      const { data } = await api.post('/device/playlists/', {
        mac: checkMac.trim().toUpperCase(),
        playlists: valid,
      });
      setPlaylistMessage({ type: 'success', text: 'Playlists saved successfully!' });
      setPlaylistFields([{ id: nextPlaylistId++, name: '', url: '' }]);
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Failed to save playlists';
      setPlaylistMessage({ type: 'error', text: msg });
    } finally {
      setSavingPlaylists(false);
    }
  };

  useEffect(() => {
    const fetchCredentials = async () => {
      setLoading(true);
      try {
        const params = filter ? { provider: filter } : {};
        const { data } = await api.get('/credentials/', { params });
        setCredentials(data.results || data);
      } catch {
        setCredentials([]);
      } finally {
        setLoading(false);
      }
    };
    fetchCredentials();
  }, [filter]);

  const handleCheckDevice = async () => {
    const trimmed = checkMac.trim().toUpperCase();
    if (!trimmed || !MAC_REGEX.test(trimmed)) {
      setCheckResult({ error: 'Enter a valid MAC address (XX:XX:XX:XX:XX:XX).' });
      return;
    }
    setChecking(true);
    setCheckResult(null);
    try {
      const { data } = await api.post('/check-device/', { mac: trimmed });
      setCheckResult(data);
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Check failed';
      setCheckResult({ error: msg });
    } finally {
      setChecking(false);
    }
  };

  const statusBadge = (result) => {
    if (result.status === 'lifetime') return 'bg-blue-200 text-blue-900';
    if (result.status === 'active') return 'bg-green-200 text-green-900';
    if (result.status === 'expiring_soon') return 'bg-yellow-200 text-yellow-900';
    if (result.status === 'expired') return 'bg-red-200 text-red-900';
    return 'bg-gray-200 text-gray-900';
  };

  const statusLabel = (result) => {
    if (result.status === 'lifetime') return 'Lifetime';
    if (result.status === 'active') return 'Active';
    if (result.status === 'expiring_soon') return 'Expiring Soon';
    if (result.status === 'expired') return 'Expired';
    return result.status;
  };

  return (
    <Layout>
      <div className="space-y-6">

        {/* Check Device Card */}
        <div className="bg-white rounded-lg shadow border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Check Device</h2>
          <p className="text-sm text-gray-500 mb-4">Look up a device by its MAC address on HotPlayer.</p>

          <div className="flex gap-2 max-w-lg">
            <input
              type="text"
              value={checkMac}
              onChange={(e) => { setCheckMac(e.target.value); setCheckResult(null); }}
              placeholder="00:1A:79:AB:CD:EF"
              maxLength={17}
              className="flex-1 px-3 py-2 border border-gray-300 rounded font-mono text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
            <button
              onClick={handleCheckDevice}
              disabled={checking}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {checking ? 'Checking...' : 'Check'}
            </button>
          </div>

          {checkResult && (
            <div className={`mt-3 p-3 rounded text-sm border max-w-lg ${
              checkResult.error
                ? 'bg-red-50 border-red-200 text-red-700'
                : checkResult.found
                  ? 'bg-green-50 border-green-200 text-green-800'
                  : 'bg-yellow-50 border-yellow-200 text-yellow-800'
            }`}>
              {checkResult.error ? (
                checkResult.error
              ) : checkResult.found ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${statusBadge(checkResult)}`}>
                      {statusLabel(checkResult)}
                    </span>
                    <span className="font-mono font-medium">{checkResult.mac}</span>
                  </div>
                  <div className="text-green-700">
                    Plan: {checkResult.plan}
                    {checkResult.expires_at && <> &middot; Expires: {checkResult.expires_at}</>}
                  </div>
                </div>
              ) : (
                <span>{checkResult.message || 'MAC not found on HotPlayer.'}</span>
              )}
            </div>
          )}

          {checkResult?.found && (
            <div className="mt-4 border-t pt-4 max-w-lg">
              <h3 className="text-sm font-semibold text-gray-700 mb-1">Add Playlists</h3>
              <p className="text-xs text-gray-500 mb-3">Add M3U URLs or XtreamCode format (HOST|USERNAME|PASSWORD)</p>

              {playlistFields.map((pf, i) => (
                <div key={pf.id} className="flex gap-2 mb-2 items-start">
                  <input
                    type="text"
                    placeholder="Name (optional)"
                    value={pf.name}
                    onChange={(e) => handlePlaylistChange(i, 'name', e.target.value)}
                    className="flex-1 px-3 py-1.5 border rounded text-sm"
                  />
                  <input
                    type="text"
                    placeholder="M3U URL or HOST|USER|PASS"
                    value={pf.url}
                    onChange={(e) => handlePlaylistChange(i, 'url', e.target.value)}
                    className="flex-[3] px-3 py-1.5 border rounded text-sm font-mono"
                  />
                  {playlistFields.length > 1 && (
                    <button onClick={() => removePlaylistField(i)} className="px-2 py-1.5 text-red-500 hover:text-red-700 text-lg">&times;</button>
                  )}
                </div>
              ))}

              <div className="flex gap-2 items-center mt-2">
                {playlistFields.length < 5 && (
                  <button onClick={addPlaylistField} className="text-sm text-indigo-600 hover:text-indigo-800 font-medium">
                    + Add another
                  </button>
                )}
                <button
                  onClick={handleSavePlaylists}
                  disabled={savingPlaylists}
                  className="ml-auto px-4 py-1.5 text-sm font-medium text-white bg-green-600 rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {savingPlaylists ? 'Saving...' : 'Save Playlists'}
                </button>
              </div>

              {playlistMessage && (
                <p className={`mt-2 text-sm ${playlistMessage.type === 'success' ? 'text-green-600' : 'text-red-600'}`}>
                  {playlistMessage.text}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Devices List */}
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">My Devices</h1>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          >
            <option value="hotplayer">HotPlayer</option>
            <option value="">All Providers</option>
          </select>
        </div>

        {loading ? (
          <div className="text-center py-12 text-gray-500">Loading devices...</div>
        ) : credentials.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            No credentials found.
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow border overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Username</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Product</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Order Date</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Expires</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Provider</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {credentials.map((cred) => (
                  <tr key={cred.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap font-mono text-sm text-gray-900">
                      {cred.username}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
                      {cred.product_name}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(cred.order_created).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {cred.expires_at
                        ? new Date(cred.expires_at).toLocaleDateString()
                        : 'Lifetime'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${PROVIDER_BADGES[cred.provider_adapter_key] || 'bg-gray-100 text-gray-800'}`}>
                        {cred.provider_adapter_key}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <Link
                        to={`/credentials/${cred.id}/manage`}
                        className="text-indigo-600 hover:text-indigo-900 font-medium"
                      >
                        Manage
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}