import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import api from '../lib/axios';

const PROVIDER_BADGES = {
  hotplayer: 'bg-purple-100 text-purple-800',
  neo4k: 'bg-blue-100 text-blue-800',
  mock: 'bg-gray-100 text-gray-800',
};

export default function DevicesPage() {
  const [credentials, setCredentials] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('hotplayer');

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

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">Devices</h1>
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
