import os
import sys
import numpy as np
import time
import tensorflow as tf
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from data_generate import *

class DNN(object):
    def __init__(self, config, node_embeddings, batch_size, optimizer, learning_rate, epoch_num):
        self.config = config
        self.batch_size = batch_size
        self.node_embeddings = node_embeddings
        self.update_embedding = False
        self.num_classes = 2  # 二分类
        self.clip = False
        self.clip_value = 5.0
        self.optimizer = optimizer
        self.learning_rate = learning_rate
        self.epoch_num = epoch_num
        self.save_path = './output/'
        self.build_graph()

    def build_graph(self):
        print('building graph ...')
        self.add_placeholders()
        self.lookup_input()
        self.fc_layer()
        self.loss_op()
        self.train_step(self.loss, self.learning_rate)
        self.variables_init_op()

    def add_placeholders(self):
        self.nodepair_input = tf.placeholder(tf.int32, [None, 2], name='nodepair_input')  # user-app pair
        self.X_input = tf.placeholder(tf.float32, [None, 202], name='X_input')
        self.y_input = tf.placeholder(tf.float32, [None, self.num_classes], name='y_input')  # y是labels，不是onehot形式

    def lookup_input(self):
        with tf.variable_scope('node_embeddings'):
            _node_embeddings = tf.get_variable('node_embeddings', shape=self.node_embeddings.shape,
                                                  initializer=tf.constant_initializer(self.node_embeddings),
                                                  trainable=self.update_embedding)
        self.nodepair_embeddings = tf.nn.embedding_lookup(
            params=_node_embeddings,
            ids=self.nodepair_input,
            name='nodepair_embeddings'
        )
        self.nodepair_embeddings = tf.reshape(self.nodepair_embeddings, [-1, 2*128])

    def fc_layer(self):
        with tf.name_scope('fc1'):
            inputs = tf.concat([self.nodepair_embeddings, self.X_input], axis=-1)
            self.input_size = inputs.get_shape().as_list()[1]
            self.w1 = tf.get_variable(name='w1', shape=[self.input_size, 512],
                                      initializer=tf.contrib.layers.xavier_initializer(), dtype=tf.float32)
            self.b1 = tf.get_variable(name='b1', shape=[512],
                                      initializer=tf.zeros_initializer(), dtype=tf.float32)
            self.l1 = tf.nn.relu(tf.matmul(inputs, self.w1) + self.b1)

        with tf.name_scope('fc2'):
            self.w2 = tf.get_variable(name='w2', shape=[512, 256],
                                      initializer=tf.contrib.layers.xavier_initializer(), dtype=tf.float32)
            self.b2 = tf.get_variable(name='b2', shape=[256],
                                      initializer=tf.zeros_initializer(), dtype=tf.float32)
            self.l2 = tf.nn.relu(tf.matmul(self.l1, self.w2) + self.b2)

        with tf.name_scope('fc3'):
            self.w3 = tf.get_variable(name='w3', shape=[256, self.num_classes],
                                      initializer=tf.contrib.layers.xavier_initializer(), dtype=tf.float32)
            self.b3 = tf.get_variable(name='b3', shape=[self.num_classes],
                                      initializer=tf.zeros_initializer(), dtype=tf.float32)
            self.logits = tf.matmul(self.l2, self.w3) + self.b3
            self.y_scores = tf.nn.softmax(self.logits)  # predictions

    def loss_op(self):
        self.loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(labels=self.y_input, logits=self.logits))

    def train_step(self, loss, learning_rate):
        self.global_step = tf.Variable(0, name='global_step', trainable=False)  # 不能梯度更新它，优化过程中是加一操作
        if self.optimizer == 'adam':
            optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
        elif self.optimizer == 'sgd':
            optimizer = tf.train.GradientDescentOptimizer(learning_rate=learning_rate)
        elif self.optimizer == 'adagrad':
            optimizer = tf.train.AdagradOptimizer(learning_rate=learning_rate)
        elif self.optimizer == 'adadelta':
            optimizer = tf.train.AdadeltaOptimizer(learning_rate=learning_rate)
        elif self.optimizer == 'rmsprop':
            optimizer = tf.train.RMSPropOptimizer(learning_rate=learning_rate)
        elif self.optimizer == 'momentum':
            optimizer = tf.train.MomentumOptimizer(learning_rate=learning_rate, momentum=0.9)
        else:
            optimizer = tf.train.GradientDescentOptimizer(learning_rate=learning_rate)
        if self.clip:
            grads_and_vars = optimizer.compute_gradients(loss)
            grads_and_vars_clipped = [[tf.clip_by_value(g, -self.clip_value, self.clip_value), v] for g, v in grads_and_vars]
            self.train_op = optimizer.apply_gradients(grads_and_vars_clipped, global_step=self.global_step) # global step在apply_gradients中加一
        else:
            self.train_op = optimizer.minimize(loss, global_step=self.global_step)  # global step在minimize函数中加一

    def variables_init_op(self):
        self.init_op = [tf.global_variables_initializer(), tf.local_variables_initializer()]

    def add_summary_op(self, sess):
        # TODO accuracy, auc等指标
        self.accuracy = self.eval_op(self.y_scores, self.y_input)
        tf.summary.scalar('accuracy', self.accuracy)
        tf.summary.scalar('loss', self.loss)
        self.merged = tf.summary.merge_all()
        self.file_writer = tf.summary.FileWriter(self.save_path + 'summary/', sess.graph)  # 保存图像

    def train(self, train_dataset, test_dataset):
        """

        :return:
        """
        print('training ...')
        saver = tf.train.Saver(tf.global_variables())
        with tf.Session() as sess:  # session config
            sess.run(self.init_op)  # variable init op
            self.add_summary_op(sess)
            for epoch in range(self.epoch_num):
                num_batches = (len(train_dataset) + self.batch_size - 1)//self.batch_size
                batches = batch_yield(train_dataset, self.batch_size, shuffle=True)
                for i, (X, labels) in enumerate(batches):
                    sys.stdout.write(' processing: {} batch / {} batches.'.format(i + 1, num_batches) + '\r')  # 回到行首
                    feed_dict = {
                        self.nodepair_input: X[:, :2],
                        self.X_input: X[:, 2:],
                        self.y_input: labels
                    }
                    _train_op, _loss, _merged, _step = sess.run([self.train_op, self.loss, self.merged, self.global_step],
                                                                feed_dict=feed_dict)
                    if i % 10 == 0:
                        self.file_writer.add_summary(_merged, _step)  # add summary
                    if i % 100 == 0:
                        accuracy = sess.run(self.accuracy, feed_dict=feed_dict)
                        print('\n epoch: %s, loss: %s, acc: %s' % (epoch+1, _loss, accuracy))
                    if i + 1 == num_batches:  # one epoch, save the model
                        saver.save(sess, self.save_path + '/model', _step)
                    if (i+1) % 300 == 0:
                        self.test(test_dataset, sess)
                self.test(test_dataset, sess)
            print('training done.')

    def evaluate_op(self, logits, labels, mode):
        """Evaluate the quality of the logits at predicting the label.
        Args:
            logits: Tensor, float
            labels: Labels tensor, float
            mode: Acc or Auc
        Returns:
            accuracy or auc
        """
        with tf.name_scope("evaluate_batch"):
            if mode == 'acc':
                predictions = tf.nn.sigmoid(logits)
                _, accuracy = tf.metrics.accuracy(tf.argmax(labels, 1), tf.argmax(predictions, 1), name='accuracy')
                return accuracy
            if mode == 'auc':
                predictions = tf.nn.sigmoid(logits)
                _, auc = tf.metrics.auc(labels, predictions, name='auc')
                return auc

    def eval_op(self, y_scores, labels):
        """

        :param y_scores: softmax scores output of MLP
        :param labels: labels, one-hot
        :return:
        """
        correct_predictions = tf.equal(tf.argmax(y_scores, 1), tf.argmax(labels, 1))
        accuracy = tf.reduce_mean(tf.cast(correct_predictions, tf.float32), name='accuracy')
        return accuracy

    def test(self, test_dataset, sess):
        batches = batch_yield(test_dataset, self.batch_size, shuffle=True)
        labels_list = []
        scores_list = []
        for i, (X, labels) in enumerate(batches):
            feed_dict = {
                self.nodepair_input: X[:, :2],
                self.X_input: X[:, 2:],
                self.y_input: labels
            }
            y_scores = sess.run(self.y_scores, feed_dict=feed_dict)
            scores_list.extend(list(np.asarray(y_scores)[:, 0]))
            labels_list.extend(list(labels[:, 0]))
        y_pred = (np.array(scores_list) > 0.5).astype('int')
        accuracy = accuracy_score(labels_list, y_pred)
        precision = precision_score(labels_list, y_pred)
        recall = recall_score(labels_list, y_pred)
        f1 = f1_score(labels_list, y_pred)
        auc = roc_auc_score(labels_list, scores_list)
        auc2 = self.auc_test(labels_list, scores_list)
        print('\n ==test== accuracy: %s, precision: %s, recall: %s, f1: %s, auc: %s, auc2: %s' % (accuracy, precision, recall,
                                                                                        f1, auc, auc2))

    def auc_test(self, y_true, y_pred):
        y_tmp = np.array(y_pred)
        y_index = y_tmp.argsort()
        y_len = len(y_index)
        area = 0
        sum_all = 0
        pos_num = 0
        neg_num = 0
        for i in range(0, y_len):
            j = y_len - i - 1
            if y_true[int(y_index[int(j)])] > 0.5:
                pos_num += 1
                area += 1
            else:
                neg_num += 1
                sum_all += area
        if neg_num == 0 or pos_num == 0:
            return 0.0
        else:
            return 1.0 * sum_all / pos_num / neg_num










