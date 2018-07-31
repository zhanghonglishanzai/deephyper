'''
 * @Author: romain.egele, dipendra.jha
 * @Date: 2018-06-20 10:23:16
'''
import os
import sys

import tensorflow as tf
import numpy as np
from pprint import pprint

HERE = os.path.dirname(os.path.abspath(__file__)) # policy dir
top  = os.path.dirname(os.path.dirname(HERE)) # search dir
top  = os.path.dirname(os.path.dirname(top)) # dir containing deephyper
sys.path.append(top)

import deephyper.model.arch as a
from deephyper.model.arch import StateSpace
from deephyper.model.utilities.conversions import action2dict_v2


class NASCellPolicy:
    def __init__(self, num_features):
        '''
            * num_feature : number of features you want to search per layer
        '''
        self.num_features = num_features

    def get(self, state, max_layers):
        with tf.name_scope('policy_network'):
            nas_cell = tf.contrib.rnn.NASCell(num_units=self.num_features*max_layers)

            outputs, state = tf.nn.dynamic_rnn(
                cell=nas_cell,
                inputs=tf.expand_dims(state, -1),
                dtype=tf.float32
                )

            bias = tf.Variable([0.05]*self.num_features*max_layers)
            outputs = tf.nn.bias_add(outputs, bias)

            # Returned last output of rnn
            return outputs[:, -1:, :]

class NASCellPolicyV2:
    def __init__(self, state_space):
        '''
            * num_feature : number of features you want to search per layer
        '''
        assert isinstance(state_space, a.StateSpace)
        self.state_space = state_space
        self.num_features = state_space.size

    def get(self, state, max_layers):
        # max_layers = number of layers for now
        with tf.name_scope('policy_network'):
            num_units = 0
            if (self.state_space.feature_is_defined('skip_conn')):
                num_units += (self.num_features-1)*max_layers
                num_units += max_layers*(max_layers+1)/2
            else:
                num_units += self.num_features*max_layers

            nas_cell = tf.contrib.rnn.NASCell(num_units)

            rnn_outputs, state = tf.nn.dynamic_rnn(
                cell=nas_cell,
                inputs=tf.expand_dims(state, -1),
                dtype=tf.float32
                )

            bias = tf.Variable([0.05]*int(num_units))
            rnn_outputs = tf.nn.bias_add(rnn_outputs, bias)

            outputs = None
            cursor = 0
            for layer_n in range(max_layers):
                for feature_i in range(self.num_features):

                    current_feature = self.state_space[feature_i]
                    if ( current_feature['name'] == 'skip_conn'):
                        # by convention-1 means input layer
                        # layer_in \in [|0, max_layers-1 |],
                        # at layer_n we can create layer_n skip_connection
                        for skip_co_i in range(layer_n+1):
                            classifier = tf.layers.dense(
                                inputs=rnn_outputs[0][cursor:cursor+1],
                                units=2,
                                name=f'classifier_skip_co_to_layer_{skip_co_i}',
                                reuse=tf.AUTO_REUSE)
                            prediction = tf.nn.softmax(classifier)
                            arg_max = tf.argmax(prediction, axis=1)
                            arg_max = tf.cast(arg_max, tf.float32)

                            if (outputs == None):
                                outputs = arg_max
                            else:
                                outputs = tf.concat(values=[outputs, arg_max], axis=0)
                            cursor += 1
                    elif ( current_feature['name'] == a.drop_out):
                        classifier = tf.layers.dense(
                            inputs=rnn_outputs[0][cursor:cursor+1],
                            units=1,
                            activation=tf.nn.sigmoid,
                            name=f'classifier_{current_feature["name"]}',
                            reuse=tf.AUTO_REUSE
                        )
                        classifier = tf.reshape(classifier, [1])

                        if (outputs == None):
                            outputs = arg_max
                        else:
                            outputs = tf.concat(values=[outputs, classifier], axis=0)
                        cursor += 1
                    else:
                        classifier = tf.layers.dense(
                            inputs=rnn_outputs[0][cursor:cursor+1],
                            units=current_feature['size'],
                            name=f'classifier_{current_feature["name"]}',
                            reuse=tf.AUTO_REUSE)
                        prediction = tf.nn.softmax(classifier)
                        arg_max = tf.argmax(prediction, axis=1)
                        arg_max = tf.cast(arg_max, tf.float32)

                        if (outputs == None):
                            outputs = arg_max
                        else:
                            outputs = tf.concat(values=[outputs, arg_max], axis=0)
                        cursor += 1

        outputs = tf.py_func(self.parse_state_tf, [outputs, max_layers], tf.float32)
        return rnn_outputs[:, -1:, :], outputs

    def parse_state_tf(self, x, num_layers):
        np_array = np.array([self.state_space.parse_state(x, num_layers)], dtype=np.float32)
        return np_array

class NASCellPolicyV3:
    def __init__(self, state_space):
        '''
            * num_feature : number of features you want to search per layer
        '''
        assert isinstance(state_space, a.StateSpace)
        self.state_space = state_space
        self.num_features = state_space.size
        self.rnn_outputs = None

    def get(self, state, max_layers):
        '''
        Args:
            state: a tensor
            max_layers: maximum number of layers
        '''
        # max_layers = number of layers for now
        with tf.name_scope('policy_network'):
            num_units = 0
            if (self.state_space.feature_is_defined('skip_conn')):
                num_units += (self.num_features-1)*max_layers
                num_units += max_layers*(max_layers+1)/2
            else:
                num_units += self.num_features*max_layers

            with tf.name_scope('RNNCell'):
                nas_cell = tf.contrib.rnn.NASCell(num_units, reuse=tf.AUTO_REUSE)

            with tf.name_scope('dynamic_rnn'):
                rnn_outputs, state = tf.nn.dynamic_rnn(
                    cell=nas_cell,
                    inputs=tf.expand_dims(state, -1),
                    dtype=tf.float32
                    )

            bias = tf.Variable([0.05]*int(num_units))
            rnn_outputs = tf.nn.bias_add(rnn_outputs, bias)
            self.rnn_outputs = rnn_outputs

            outputs = []
            cursor = 0
            with tf.name_scope('outputs'):
                for layer_n in range(max_layers):
                    for feature_i in range(self.num_features):

                        current_feature = self.state_space[feature_i]
                        if ( current_feature['name'] == 'skip_conn'):
                            # by convention-1 means input layer
                            # layer_in \in [|0, max_layers-1 |],
                            # at layer_n we can create layer_n skip_connection
                            for skip_co_i in range(layer_n+1):
                                classifier = tf.layers.dense(
                                    inputs=rnn_outputs[0][cursor:cursor+1],
                                    units=2,
                                    name=f'classifier_skip_co_to_layer_{skip_co_i}',
                                    reuse=tf.AUTO_REUSE)
                                prediction = tf.nn.softmax(classifier)
                                arg_max = tf.argmax(prediction, axis=1)
                                arg_max = tf.cast(arg_max, tf.float32)

                                outputs.append(arg_max)
                                cursor += 1
                        elif ( current_feature['name'] == a.drop_out):
                            classifier = tf.layers.dense(
                                inputs=rnn_outputs[0][cursor:cursor+1],
                                units=1,
                                activation=tf.nn.sigmoid,
                                name=f'classifier_{current_feature["name"]}',
                                reuse=tf.AUTO_REUSE
                            )
                            classifier = tf.reshape(classifier, [1])

                            outputs.append(classifier)
                            cursor += 1
                        else:
                            classifier = tf.layers.dense(
                                inputs=rnn_outputs[0][cursor:cursor+1],
                                units=current_feature['size'],
                                name=f'classifier_{current_feature["name"]}',
                                reuse=tf.AUTO_REUSE)
                            prediction = tf.nn.softmax(classifier)
                            arg_max = tf.argmax(prediction, axis=1)
                            arg_max = tf.cast(arg_max, tf.float32)

                            outputs.append(arg_max)
                            cursor += 1

        self.outputs_before_py_func = outputs
        #outputs = tf.py_func(self.parse_state_tf, [outputs, num_layers], tf.float32)
        return rnn_outputs[:, -1:, :], outputs

    def parse_state_tf(self, x, num_layers):
        np_array = np.array([self.state_space.parse_state(x, num_layers)], dtype=np.float32)
        return np_array

def initialize_uninitialized(sess):
    global_vars          = tf.global_variables()
    is_not_initialized   = sess.run([tf.is_variable_initialized(var) for var in global_vars])
    not_initialized_vars = [v for (v, f) in zip(global_vars, is_not_initialized) if not f]

    print([str(i.name) for i in not_initialized_vars]) # only for testing
    if len(not_initialized_vars):
        sess.run(tf.variables_initializer(not_initialized_vars))

def test_NASCellPolicyV2():
    max_layers = 3
    sp = a.StateSpace()
    sp.add_state('filter_size', [10., 20., 30.])
    sp.add_state('drop_out', [])
    sp.add_state('num_filters', [32., 64.])
    sp.add_state('skip_conn', [])
    policy = NASCellPolicyV2(sp)
    state = [[10., 0.5, 32., 1.,
              10., 0.5, 32., 1., 1.,
              10., 0.5, 32., 1., 1., 1.]]
    print(f'hand = {state[0]}, length = {len(state[0])}')
    state = sp.get_random_state_space(max_layers)
    print(f'auto = {state[0]}, length = {len(state[0])}')
    cfg = {}
    cfg[a.layer_type] = a.conv1D
    cfg['state_space'] = sp
    pprint(action2dict_v2(cfg, state[0], max_layers))
    #state = [[10., 10.]]
    if (sp.feature_is_defined('skip_conn')):
        seq_length = (sp.size-1)*max_layers
        seq_length += max_layers*(max_layers+1)/2
    else:
        seq_length = sp.size*max_layers
    with tf.name_scope("model_inputs"):
        ph_states = tf.placeholder(
            tf.float32, [None, seq_length], name="states")
    _, net_outputs = policy.get(ph_states, max_layers)

    with tf.Session() as sess:
        init = tf.global_variables_initializer()
        sess.run(init)
        res1 = sess.run([net_outputs], {ph_states: state})
        print('Prediction : ')
        pprint(res1[0][0])
        pprint(action2dict_v2(cfg, res1[0][0], max_layers))

def test_NASCellPolicyV3():
    max_layers = 3

    sp = a.StateSpace()
    sp.add_state('filter_size', [10., 20., 30.])
    sp.add_state('drop_out', [])
    sp.add_state('num_filters', [32., 64.])
    sp.add_state('skip_conn', [])
    policy = NASCellPolicyV3(sp)

    # STATE with 2 layers
    state_l2 = [[10., 0.5, 32., 1.,
                 10., 0.5, 32., 1., 1.]]
    num_layers = 2
    print(f'Input = {state_l2[0]}, length = {len(state_l2[0])}')
    with tf.name_scope("model_inputs"):
        ph_states = tf.placeholder(
            tf.float32, [None, None], name="states")
    o1, net_outputs = policy.get(ph_states, max_layers)
    with tf.Session() as sess:
        init = tf.global_variables_initializer()
        tf.summary.FileWriter('graph', graph=tf.get_default_graph())
        sess.run(init)
        res1 = sp.parse_state(np.array(sess.run(net_outputs[:len(state_l2[0])], {ph_states: state_l2})).flatten().tolist(), num_layers)
        print(f'Predict = {res1}, length = {len(res1)} ')

        # STATE with 3 layers
        state_l3 = [[10., 0.5, 32., 1.,
                    10., 0.5, 32., 1., 1.,
                    10., 0.5, 32., 1., 1., 1.]]
        num_layers = 3
        print(f'Input = {state_l3[0]}, length = {len(state_l3[0])}')
        res1 = sp.parse_state(np.array(sess.run(net_outputs[:len(state_l3[0])], {ph_states: state_l3})).flatten().tolist(), num_layers)
        print(f'Predict = {res1}, length = {len(res1)} ')

if __name__ == '__main__':
    test_NASCellPolicyV3()
