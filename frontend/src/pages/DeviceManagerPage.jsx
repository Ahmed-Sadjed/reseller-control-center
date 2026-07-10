import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import api from '../lib/axios';

export default function DeviceManagerPage() {
  const { credentialId } = useParams();
  const navigate = useNavigate();
  const [credential, setCredential] = useState(null);
  const [deviceInfo, setDeviceInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState(false);
  const [playlists, setPlaylists] = useState([{ name: '', url: '' }]);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState(null);

  const showMessage = useCallback((text, isError = false) => {
    setMessage({ text, isError });
  }, []);

  const fetchDeviceStatus = useCallback(async () => {
    try {
      const { data } = await api.get(`/credentials/${credentialId}/device/status/`);
      setDeviceInfo(data);
    } catch (err) {
      showMessage(err.response?.data?.error || 'Failed to check device', true);
    }
  }, [credentialId, showMessage]);

  useEffect(() => {
    const fetchCredential = async () => {
      try {
        const { data } = await api.get(`/orders/`);
        const results = data.results
          ? await Promise.allSettled(
              data.results.map((o) => api.get(`/orders/${o.uuid}/credentials/`).then((r) => r.data))
            )
          : [];
        const allCreds = results
          .filter((r) => r.status === 'fulfilled')
          .flatMap((r) => r.value);
        const cred = allCreds.find((c) => String(c.id) === credentialId);
        if (cred) {
          setCredential(cred);
        }
      } catch {
        showMessage('Failed to load credential', true);
      } finally {
        setLoading(false);
      }
    };
    fetchCredential();
    fetchDeviceStatus();
  }, [credentialId, fetchDeviceStatus, showMessage]);

  const handleActivate = async (duration) => {
    setActivating(true);
    setMessage(null);
    try {
      const { data } = await api.post(`/credentials/${credentialId}/device/activate/`, {
        pack_id: credential?.external_pack_id || 1,
        duration,
        extend: true,
      });
      showMessage('Device extended successfully!');
      await fetchDeviceStatus();
    } catch (err) {
      showMessage(err.response?.data?.error || 'Activation failed', true);
    } finally {
      setActivating(false);
    }
  };

  const handleAddPlaylists = async () => {
    const valid = playlists.filter((p) => p.url.trim());
    if (valid.length === 0) {
      showMessage('Enter at least one playlist URL', true);
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await api.post(`/credentials/${credentialId}/device/playlists/`, { playlists: valid });
      showMessage('Playlists added!');
      setPlaylists([{ name: '', url: '' }]);
      await fetchDeviceStatus();
    } catch (err) {
      showMessage(err.response?.data?.error || 'Failed to add playlists', true);
    } finally {
      setSaving(false);
    }
  };

  const handleDeletePlaylists = async () => {
    if (!window.confirm('Delete all playlists from this device?')) return;
    setDeleting(true);
    setMessage(null);
    try {
      await api.delete(`/credentials/${credentialId}/device/playlists/`);
      showMessage('All playlists deleted');
      setDeviceInfo((prev) => (prev ? { ...prev, playlists: [] } : prev));
    } catch (err) {
      showMessage(err.response?.data?.error || 'Failed to delete playlists', true);
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="text-center py-12 text-gray-500">Loading device...</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Device Management</h1>
            <p className="text-sm text-gray-500">
              Credential #{credentialId}{credential ? ` - ${credential.username}` : ''}
            </p>
          </div>
          <button
            onClick={() => navigate(-1)}
            className="text-sm text-indigo-600 hover:text-indigo-800"
          >
            &larr; Back
          </button>
        </div>

        {message && (
          <div className={`p-3 rounded text-sm ${message.isError ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`}>
            {message.text}
          </div>
        )}

        {deviceInfo && (
          <div className="bg-white rounded-lg shadow border p-6">
            <h2 className="text-lg font-semibold mb-4">Device Status</h2>
            <dl className="grid grid-cols-2 gap-4">
              <div>
                <dt className="text-xs text-gray-500">MAC</dt>
                <dd className="font-mono text-sm">{deviceInfo.mac || credential?.username}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Status</dt>
                <dd className="text-sm capitalize">{deviceInfo.status || 'Unknown'}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Plan</dt>
                <dd className="text-sm">{deviceInfo.plan || '-'}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Expires</dt>
                <dd className="text-sm">
                  {deviceInfo.expiration ? new Date(deviceInfo.expiration).toLocaleDateString() : 'Lifetime'}
                </dd>
              </div>
            </dl>
            <div className="mt-4 flex gap-3">
              <button
                onClick={() => handleActivate('YEAR_1')}
                disabled={activating}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50"
              >
                {activating ? 'Processing...' : 'Extend 12 Months'}
              </button>
              <button
                onClick={() => handleActivate('FOREVER')}
                disabled={activating}
                className="px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded hover:bg-purple-700 disabled:opacity-50"
              >
                {activating ? 'Processing...' : 'Extend Lifetime'}
              </button>
            </div>
          </div>
        )}

        {deviceInfo && deviceInfo.playlists && deviceInfo.playlists.length > 0 && (
          <div className="bg-white rounded-lg shadow border p-6">
            <h2 className="text-lg font-semibold mb-4">Current Playlists</h2>
            <ul className="space-y-2">
              {deviceInfo.playlists.map((p, i) => (
                <li key={i} className="text-sm text-gray-700 truncate">
                  {p.name ? <span className="font-medium">{p.name}: </span> : ''}
                  {p.url}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="bg-white rounded-lg shadow border p-6">
          <h2 className="text-lg font-semibold mb-4">Add Playlists</h2>
          {playlists.map((p, idx) => (
            <div key={idx} className="flex gap-2 mb-2">
              <input
                type="text"
                placeholder="Name (optional)"
                value={p.name}
                onChange={(e) => {
                  const next = [...playlists];
                  next[idx] = { ...next[idx], name: e.target.value };
                  setPlaylists(next);
                }}
                className="flex-1 border rounded px-3 py-2 text-sm"
              />
              <input
                type="text"
                placeholder="M3U URL or Xtream URL"
                value={p.url}
                onChange={(e) => {
                  const next = [...playlists];
                  next[idx] = { ...next[idx], url: e.target.value };
                  setPlaylists(next);
                }}
                className="flex-[2] border rounded px-3 py-2 text-sm"
              />
              {playlists.length > 1 && (
                <button
                  onClick={() => setPlaylists(playlists.filter((_, i) => i !== idx))}
                  className="text-red-500 px-2 text-lg"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
          {playlists.length < 5 && (
            <button
              onClick={() => setPlaylists([...playlists, { name: '', url: '' }])}
              className="text-sm text-indigo-600 hover:text-indigo-800"
            >
              + Add another playlist
            </button>
          )}
          <div className="mt-4 flex gap-3">
            <button
              onClick={handleAddPlaylists}
              disabled={saving}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save Playlists'}
            </button>
            <button
              onClick={handleDeletePlaylists}
              disabled={deleting}
              className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded hover:bg-red-700 disabled:opacity-50"
            >
              {deleting ? 'Deleting...' : 'Delete All Playlists'}
            </button>
          </div>
        </div>
      </div>
    </Layout>
  );
}
