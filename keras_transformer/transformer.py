import keras
from keras_layer_normalization import LayerNormalization
from keras_multi_head import MultiHeadAttention
from keras_position_wise_feed_forward import FeedForward
from keras_pos_embd import TrigPosEmbedding


def get_custom_objects():
    return {
        'LayerNormalization': LayerNormalization,
        'MultiHeadAttention': MultiHeadAttention,
        'FeedForward': FeedForward,
        'TrigPosEmbedding': TrigPosEmbedding,
    }


def _wrap_layer(name, input_layer, build_func, dropout_rate=0.0):
    """Wrap layers with residual, normalization and dropout.

    :param name: Prefix of names for internal layers.
    :param input_layer: Input layer.
    :param build_func: A callable that takes the input tensor and generates the output tensor.
    :param dropout_rate: Dropout rate.
    :return: Output layer.
    """
    build_output = build_func(input_layer)
    normal_layer = LayerNormalization(name='%s-Norm' % name)(build_output)
    if dropout_rate > 0.0:
        dropout_layer = keras.layers.Dropout(
            rate=dropout_rate,
            name='%s-Dropout' % name,
        )(normal_layer)
    else:
        dropout_layer = normal_layer
    if isinstance(input_layer, list):
        input_layer = input_layer[0]
    output_layer = keras.layers.Add(name='%s-Add' % name)([input_layer, dropout_layer])
    return output_layer


def _attention_builder(name, head_num, activation, history_only):
    """Get multi-head self-attention builder.

    :param name: Prefix of names for internal layers.
    :param head_num: Number of heads in multi-head self-attention.
    :param activation: Activation for multi-head self-attention.
    :param history_only: Only use history data.
    :return:
    """
    def __attention_builder(x):
        return MultiHeadAttention(
            head_num=head_num,
            activation=activation,
            history_only=history_only,
            name=name,
        )(x)
    return __attention_builder


def _feed_forward_builder(name, hidden_dim, activation):
    """Get position-wise feed-forward layer builder.

    :param name: Prefix of names for internal layers.
    :param hidden_dim: Hidden dimension of feed forward layer.
    :param activation: Activation for feed-forward layer.
    :return:
    """
    def __feed_forward_builder(x):
        return FeedForward(
            units=hidden_dim,
            activation=activation,
            name=name,
        )(x)
    return __feed_forward_builder


def _get_encoder_component(name, input_layer, head_num, hidden_dim, activation='relu', dropout_rate=0.0):
    """Multi-head self-attention and feed-forward layer.

    :param name: Prefix of names for internal layers.
    :param input_layer: Input layer.
    :param head_num: Number of heads in multi-head self-attention.
    :param hidden_dim: Hidden dimension of feed forward layer.
    :param activation: Activation for multi-head self-attention and feed-forward layer.
    :param dropout_rate: Dropout rate.
    :return: Output layer.
    """
    attention_name = '%s-MultiHeadSelfAttention' % name
    feed_forward_name = '%s-FeedForward' % name
    attention_layer = _wrap_layer(
        name=attention_name,
        input_layer=input_layer,
        build_func=_attention_builder(
            name=attention_name,
            head_num=head_num,
            activation=activation,
            history_only=False,
        ),
        dropout_rate=dropout_rate,
    )
    feed_forward_layer = _wrap_layer(
        name=feed_forward_name,
        input_layer=attention_layer,
        build_func=_feed_forward_builder(
            name=feed_forward_name,
            hidden_dim=hidden_dim,
            activation=activation,
        ),
        dropout_rate=dropout_rate,
    )
    return feed_forward_layer


def _get_decoder_component(name, input_layer, encoded_layer, head_num, hidden_dim, activation='relu', dropout_rate=0.0):
    """Multi-head self-attention, multi-head query attention and feed-forward layer.

    :param name: Prefix of names for internal layers.
    :param input_layer: Input layer.
    :param encoded_layer: Encoded layer from encoder.
    :param head_num: Number of heads in multi-head self-attention.
    :param hidden_dim: Hidden dimension of feed forward layer.
    :param activation: Activation for multi-head self-attention and feed-forward layer.
    :param dropout_rate: Dropout rate.
    :return: Output layer.
    """
    self_attention_name = '%s-MultiHeadSelfAttention' % name
    query_attention_name = '%s-MultiHeadQueryAttention' % name
    feed_forward_name = '%s-FeedForward' % name
    self_attention_layer = _wrap_layer(
        name=self_attention_name,
        input_layer=input_layer,
        build_func=_attention_builder(
            name=self_attention_name,
            head_num=head_num,
            activation=activation,
            history_only=True,
        ),
        dropout_rate=dropout_rate,
    )
    query_attention_layer = _wrap_layer(
        name=query_attention_name,
        input_layer=[self_attention_layer, encoded_layer, encoded_layer],
        build_func=_attention_builder(
            name=query_attention_name,
            head_num=head_num,
            activation=activation,
            history_only=False,
        ),
        dropout_rate=dropout_rate,
    )
    feed_forward_layer = _wrap_layer(
        name=feed_forward_name,
        input_layer=query_attention_layer,
        build_func=_feed_forward_builder(
            name=feed_forward_name,
            hidden_dim=hidden_dim,
            activation=activation,
        ),
        dropout_rate=dropout_rate,
    )
    return feed_forward_layer


def get_encoders(encoder_num, input_layer, head_num, hidden_dim, activation='relu', dropout_rate=0.0):
    """Get encoders.

    :param encoder_num: Number of encoder components.
    :param input_layer: Input layer.
    :param head_num: Number of heads in multi-head self-attention.
    :param hidden_dim: Hidden dimension of feed forward layer.
    :param activation: Activation for multi-head self-attention and feed-forward layer.
    :param dropout_rate: Dropout rate.
    :return: Output layer.
    """
    last_layer = input_layer
    for i in range(encoder_num):
        last_layer = _get_encoder_component(
            name='Encoder-%d' % (i + 1),
            input_layer=last_layer,
            head_num=head_num,
            hidden_dim=hidden_dim,
            activation=activation,
            dropout_rate=dropout_rate,
        )
    return last_layer


def get_decoders(decoder_num, input_layer, encoded_layer, head_num, hidden_dim, activation='relu', dropout_rate=0.0):
    """Get decoders.

    :param decoder_num: Number of decoder components.
    :param input_layer: Input layer.
    :param encoded_layer: Encoded layer from encoder.
    :param head_num: Number of heads in multi-head self-attention.
    :param hidden_dim: Hidden dimension of feed forward layer.
    :param activation: Activation for multi-head self-attention and feed-forward layer.
    :param dropout_rate: Dropout rate.
    :return: Output layer.
    """
    last_layer = input_layer
    for i in range(decoder_num):
        last_layer = _get_decoder_component(
            name='Decoder-%d' % (i + 1),
            input_layer=last_layer,
            encoded_layer=encoded_layer,
            head_num=head_num,
            hidden_dim=hidden_dim,
            activation=activation,
            dropout_rate=dropout_rate,
        )
    return last_layer


def get_model(token_num,
              embed_dim,
              encoder_num,
              decoder_num,
              head_num,
              hidden_dim,
              activation='relu',
              dropout_rate=0.0,
              embed_weights=None,
              embed_trainable=None):
    """Get full model without compilation.

    :param token_num: Number of distinct tokens.
    :param embed_dim: Dimension of token embedding.
    :param encoder_num: Number of encoder components.
    :param decoder_num: Number of decoder components.
    :param head_num: Number of heads in multi-head self-attention.
    :param hidden_dim: Hidden dimension of feed forward layer.
    :param activation: Activation for multi-head self-attention and feed-forward layer.
    :param dropout_rate: Dropout rate.
    :param embed_weights: Initial weights of token embedding.
    :param embed_trainable: Whether the token embedding is trainable. It will automatically set to False if the given
                            value is None when embedding weights has been provided.
    :return: Keras model.
    """
    if embed_weights is not None:
        if not isinstance(embed_weights, list):
            embed_weights = [embed_weights]
    if embed_trainable is None:
        embed_trainable = embed_weights is None
    embed_layer = keras.layers.Embedding(
        input_dim=token_num,
        output_dim=embed_dim,
        weights=embed_weights,
        trainable=embed_trainable,
        name='Token-Embedding',
    )
    encoder_input = keras.layers.Input(shape=(None,), name='Encoder-Input')
    encoder_embed = TrigPosEmbedding(
        mode=TrigPosEmbedding.MODE_ADD,
        name='Encoder-Embedding',
    )(embed_layer(encoder_input))
    encoded_layer = get_encoders(
        encoder_num=encoder_num,
        input_layer=encoder_embed,
        head_num=head_num,
        hidden_dim=hidden_dim,
        activation=activation,
        dropout_rate=dropout_rate,
    )
    decoder_input = keras.layers.Input(shape=(None,), name='Decoder-Input')
    decoder_embed = TrigPosEmbedding(
        mode=TrigPosEmbedding.MODE_ADD,
        name='Decoder-Embedding',
    )(embed_layer(decoder_input))
    decoded_layer = get_decoders(
        decoder_num=decoder_num,
        input_layer=decoder_embed,
        encoded_layer=encoded_layer,
        head_num=head_num,
        hidden_dim=hidden_dim,
        activation=activation,
        dropout_rate=dropout_rate,
    )
    dense_layer = keras.layers.Dense(
        units=token_num,
        activation='softmax',
        name='Output',
    )(decoded_layer)
    return keras.models.Model(inputs=[encoder_input, decoder_input], outputs=dense_layer)