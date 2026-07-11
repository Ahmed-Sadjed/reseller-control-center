import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import api from '../lib/axios';

export default function LineManagerPage() {
  const { credentialId } = useParams();
  const navigate = useNavigate();
  const [credential, setCredential] = useState(null);
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [extending, setExtending] = useState(false);
  const [refunding, setRefunding] = useState(false);
  const [message, setMessage] = useState(null);
  const [selectedVariant, setSelectedVariant] = useState(null);

  const showMessage = useCallback((text, isError = false) => {
    setMessage({ text, isError });
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Fetch credentials to find the current one
        const { data } = await api.get('/orders/');
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
          // Fetch product to get variants for extension
          const productRes = await api.get('/products/');
          const products = productRes.data.results || productRes.data;
          const prod = products.find((p) => p.id === cred.product_id);
          if (prod) {
            setProduct(prod);
            if (prod.variants && prod.variants.length > 0) {
              setSelectedVariant(prod.variants[0]);
            }
          }
        }
      } catch (err) {
        showMessage('Failed to load line data', true);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [credentialId, showMessage]);

  const handleExtend = async () => {
    if (!selectedVariant) {
      showMessage('Please select a package to extend', true);
      return;
    }
    setExtending(true);
    setMessage(null);
    try {
      await api.post(`/credentials/${credentialId}/device/activate/`, {
        pack_id: selectedVariant.external_pack_id,
        duration: selectedVariant.display_name === 'Lifetime' ? 'FOREVER' : 'YEAR_1', // Not strictly used for golden API since pack_id handles duration, but required by schema
        extend: true,
      });
      showMessage('Line extended successfully!');
      // Update credential expires_at by refetching or just display success
    } catch (err) {
      showMessage(err.response?.data?.error || 'Extension failed', true);
    } finally {
      setExtending(false);
    }
  };

  const handleRefund = async () => {
    if (!window.confirm('Are you sure you want to refund this line? This will permanently cancel the line and refund your credits.')) {
      return;
    }
    setRefunding(true);
    setMessage(null);
    try {
      await api.post(`/credentials/${credentialId}/device/refund/`);
      showMessage('Line refunded successfully. Credits have been returned.');
      setCredential(prev => ({ ...prev, is_revoked: true }));
    } catch (err) {
      showMessage(err.response?.data?.error || 'Refund failed', true);
    } finally {
      setRefunding(false);
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="text-center py-12 text-gray-500">Loading line data...</div>
      </Layout>
    );
  }

  if (!credential) {
    return (
      <Layout>
        <div className="text-center py-12 text-red-500">Line not found.</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Line Management</h1>
            <p className="text-sm text-gray-500">
              Username: {credential.username}
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

        <div className="bg-white rounded-lg shadow border p-6">
          <h2 className="text-lg font-semibold mb-4">Line Status</h2>
          <dl className="grid grid-cols-2 gap-4">
            <div>
              <dt className="text-xs text-gray-500">Username</dt>
              <dd className="font-mono text-sm">{credential.username}</dd>
            </div>
            <div>
              <dt className="text-xs text-gray-500">Password</dt>
              <dd className="font-mono text-sm">{credential.credential_data?.secret_password || '••••••••'}</dd>
            </div>
            <div>
              <dt className="text-xs text-gray-500">Status</dt>
              <dd className="text-sm">
                {credential.is_revoked ? (
                  <span className="text-red-600 font-semibold">Revoked / Refunded</span>
                ) : (
                  <span className="text-green-600 font-semibold">Active</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-gray-500">Expires</dt>
              <dd className="text-sm">
                {credential.expires_at ? new Date(credential.expires_at).toLocaleDateString() : 'Lifetime'}
              </dd>
            </div>
          </dl>
          
          {!credential.is_revoked && (
            <div className="mt-6 border-t pt-6">
              <h3 className="text-md font-medium text-gray-900 mb-3">Extend Line</h3>
              {product && product.variants && product.variants.length > 0 ? (
                <div className="flex items-end gap-3">
                  <div className="flex-1">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Select Package</label>
                    <select
                      className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-indigo-500 focus:border-indigo-500"
                      value={selectedVariant?.id || ''}
                      onChange={(e) => {
                        const variant = product.variants.find(v => String(v.id) === e.target.value);
                        setSelectedVariant(variant);
                      }}
                    >
                      {product.variants.map(v => (
                        <option key={v.id} value={v.id}>
                          {v.display_name} - {v.price_in_credits} Credits
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    onClick={handleExtend}
                    disabled={extending || !selectedVariant}
                    className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {extending ? 'Extending...' : 'Extend Line'}
                  </button>
                </div>
              ) : (
                <p className="text-sm text-gray-500">No extension packages available for this product.</p>
              )}
            </div>
          )}

          {!credential.is_revoked && (
            <div className="mt-6 border-t pt-6">
              <h3 className="text-md font-medium text-red-700 mb-2">Cancel & Refund</h3>
              <p className="text-sm text-gray-500 mb-3">
                Refunds will permanently cancel the line and return the original credits to your balance.
              </p>
              <button
                onClick={handleRefund}
                disabled={refunding}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded hover:bg-red-700 disabled:opacity-50"
              >
                {refunding ? 'Processing Refund...' : 'Refund Line'}
              </button>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
